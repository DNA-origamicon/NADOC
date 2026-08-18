"""Focused checks for the local native-OpenXR bridge."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import routes_vr
from backend.api.routes_vr import (
    VRFeedbackRequest,
    VRCamera,
    _bundle_expanded_scene,
    _event_payload,
    _expanded_helix_offsets,
    _expanded_scene_inputs,
    _require_local,
    _serialize_scene,
    _write_feedback,
)


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
    version = int(text.splitlines()[0].split()[1])
    for line in text.splitlines():
        record = line.split()
        if not record or record[0] == "#":
            continue
        if record[0] == "R":
            active = record[1]
            sections[active] = []
        elif record[0] in {"P", "C", "H", "B"}:
            if version >= 6:
                record = [record[0], *record[2:]]
            sections[active].append(record)
    return sections


def _scene_identities(text: str) -> dict[str, list[str]]:
    identities: dict[str, list[str]] = {}
    active = ""
    for line in text.splitlines():
        record = line.split()
        if not record or record[0] == "#":
            continue
        if record[0] == "R":
            active = record[1]
            identities[active] = []
        elif record[0] in {"P", "C", "H", "B"}:
            identities[active].append(record[1])
    return identities


def test_native_vr_routes_are_workstation_only() -> None:
    _require_local(_request("127.0.0.1", "http://localhost:5173"))
    with pytest.raises(HTTPException, match="localhost"):
        _require_local(_request("192.0.2.4"))
    with pytest.raises(HTTPException, match="localhost"):
        _require_local(_request("127.0.0.1", "http://192.0.2.4:5173"))


def test_expanded_quick_view_matches_desktop_centroid_spacing() -> None:
    point = lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)
    design = SimpleNamespace(
        helices=[
            SimpleNamespace(id="left", axis_start=point(-1, 0, 0), axis_end=point(-1, 0, 10)),
            SimpleNamespace(id="right", axis_start=point(1, 0, 0), axis_end=point(1, 0, 10)),
        ],
        strands=[],
        extensions=[],
    )

    offsets = _expanded_helix_offsets(design)

    expected = (5.0 / 2.25 - 1.0)
    np.testing.assert_allclose(offsets["left"], [-expected, 0, 0])
    np.testing.assert_allclose(offsets["right"], [expected, 0, 0])


def test_expanded_scene_translates_owners_and_interpolates_crossover_atoms() -> None:
    point = lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)
    design = SimpleNamespace(
        helices=[
            SimpleNamespace(id="a", axis_start=point(-1, 0, 0), axis_end=point(-1, 0, 10)),
            SimpleNamespace(id="b", axis_start=point(1, 0, 0), axis_end=point(1, 0, 10)),
        ],
        strands=[],
        extensions=[],
    )
    nucleotides = [
        {
            "helix_id": "a",
            "backbone_position": [-1, 2, 3],
            "base_position": [-0.8, 2, 3],
        }
    ]
    axes = [{"helix_id": "b", "start": [1, 0, 0], "end": [1, 0, 10]}]
    atom = SimpleNamespace(
        helix_id="a", aux_helix_id="b", aux_t=0.25, x=0.0, y=0.0, z=0.0
    )

    expanded_nucleotides, expanded_axes, expanded_model = _expanded_scene_inputs(
        design, nucleotides, axes, SimpleNamespace(atoms=[atom], bonds=[])
    )

    delta = 5.0 / 2.25 - 1.0
    np.testing.assert_allclose(
        expanded_nucleotides[0]["backbone_position"], [-1 - delta, 2, 3]
    )
    np.testing.assert_allclose(expanded_axes[0]["start"], [1 + delta, 0, 0])
    assert expanded_model.atoms[0].x == pytest.approx(-0.5 * delta)
    assert atom.x == 0.0  # source inputs remain immutable


def test_v7_bundle_pairs_natural_and_expanded_primitives_by_identity() -> None:
    natural = """NADOCVR 6 full strand
R full
P owner 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
"""
    expanded = natural.replace("P owner 0 0 0", "P owner 2 0 0")

    bundled = _bundle_expanded_scene(natural, expanded)

    assert bundled.startswith("NADOCVR 7 full strand\n")
    assert "R full\nP owner 0 0 0" in bundled
    assert "E full\nP owner 2 0 0" in bundled

    mismatched = expanded.replace("owner", "different")
    with pytest.raises(HTTPException, match="identities differ"):
        _bundle_expanded_scene(natural, mismatched)


def test_native_event_reader_is_bounded_and_tolerates_partial_writes(tmp_path) -> None:
    event_path = tmp_path / "vr-event.json"
    event_path.write_text(
        '{"sequence":7,"hover_identity":"nuc:s1:0:h1:4:FORWARD:0",'
        '"select_sequence":2,"select_identity":"nuc:s1:0:h1:3:FORWARD:0",'
        '"level_sequence":3,"selection_level":"domain"}'
    )
    assert _event_payload({"event_path": str(event_path)}) == {
        "sequence": 7,
        "hover_identity": "nuc:s1:0:h1:4:FORWARD:0",
        "select_sequence": 2,
        "select_identity": "nuc:s1:0:h1:3:FORWARD:0",
        "level_sequence": 3,
        "selection_level": "domain",
    }

    event_path.write_text('{"sequence":')
    assert _event_payload({"event_path": str(event_path)}) == {
        "sequence": 0,
        "hover_identity": None,
        "select_sequence": 0,
        "select_identity": None,
        "level_sequence": 0,
        "selection_level": "default",
    }

    event_path.write_text("x" * 4097)
    assert _event_payload({"event_path": str(event_path)})["sequence"] == 0


def test_native_feedback_writer_is_private_bounded_and_atomic(tmp_path) -> None:
    feedback_path = tmp_path / "vr-feedback.txt"
    feedback_path.write_text("NADOCVR_FEEDBACK 1 0 0 0 default -\n")
    _write_feedback(
        {"feedback_path": str(feedback_path)},
        VRFeedbackRequest(
            select_sequence=4,
            identity="nuc:s1:0:h1:3:FORWARD:0",
            accepted=True,
            selected=True,
            selection_level="base",
        ),
    )
    assert feedback_path.read_text() == (
        "NADOCVR_FEEDBACK 1 4 1 1 base nuc:s1:0:h1:3:FORWARD:0\n"
    )
    assert feedback_path.stat().st_mode & 0o777 == 0o600
    assert not feedback_path.with_name(f"{feedback_path.name}.next").exists()

    with pytest.raises(HTTPException, match="Invalid VR feedback identity"):
        _write_feedback(
            {"feedback_path": str(feedback_path)},
            VRFeedbackRequest(select_sequence=5, identity="not whitespace safe"),
        )


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
    identities = _scene_identities(text)

    assert text.startswith("NADOCVR 6 full strand\n")
    assert set(sections) == {"full", "cylinders", "ballstick", "stick"}
    assert all(len(values) == len(set(values)) for values in identities.values())
    assert "nuc:s1:0:h1:1:FORWARD:0:backbone" in identities["full"]
    assert "atom:0:base:h1:0:FORWARD:C" in identities["ballstick"]
    assert (
        "atom-bond:bases:h1:0:FORWARD~h1:1:FORWARD:atoms:0-1"
        in identities["ballstick"]
    )
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
    boxes = [
        [record[0], *record[2:]]
        for line in text.splitlines()
        if line.startswith("B ")
        for record in [line.split()]
    ]
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
                id="xo-visible",
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
                id="xo-extra",
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
    identities = _scene_identities(text)

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
    assert any(
        identity.startswith("linker:link:ss:backbone:0:near:0")
        for identity in identities["full"]
    )
    assert any(
        identity.endswith(":near:1")
        for identity in identities["full"]
        if identity.startswith("linker:link:ss:backbone:")
    )
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


def test_flexible_segment_replaces_filtered_beads_in_full_only() -> None:
    domains = [
        SimpleNamespace(
            helix_id=helix_id,
            start_bp=bp,
            end_bp=bp,
            direction="FORWARD",
        )
        for helix_id, bp in (("ha", 2), ("run", 0), ("hb", 7))
    ]
    strand = SimpleNamespace(
        id="flex-strand",
        is_scaffold=False,
        color="#0066cc",
        sequence="AAAA",
        domains=domains,
        strand_type="staple",
    )
    anchor_a = SimpleNamespace(
        strand_id="flex-strand",
        domain_index=0,
        bp_index=2,
        direction="FORWARD",
    )
    anchor_b = SimpleNamespace(
        strand_id="flex-strand",
        domain_index=2,
        bp_index=7,
        direction="FORWARD",
    )
    design = SimpleNamespace(
        strands=[strand],
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
        overhang_bindings=[],
        duplexes=[],
        overhang_connections=[],
        flexible_connections=[
            SimpleNamespace(
                id="flex-1",
                anchor_a=anchor_a,
                anchor_b=anchor_b,
                n_ss_bases=2,
                contour_length_nm=5.0,
            )
        ],
    )
    nucleotides = [
        {
            "strand_id": "flex-strand",
            "domain_index": domain_index,
            "helix_id": helix_id,
            "bp_index": bp,
            "direction": "FORWARD",
            "backbone_position": position,
            "is_flexible_segment": flexible,
        }
        for domain_index, helix_id, bp, position, flexible in (
            (0, "ha", 2, [0, 0, 0], False),
            (1, "run", 0, [1, 0, 0], True),
            (1, "run", 1, [3, 0, 0], True),
            (2, "hb", 7, [4, 0, 0], False),
        )
    ]
    text = _serialize_scene(
        design,
        nucleotides,
        [{"helix_id": "obstacle", "start": [0, -1, -1], "end": [4, -1, -1]}],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    sections = _scene_sections(text)
    identities = _scene_identities(text)

    assert (
        sum(
            record[0] == "P" and float(record[4]) == pytest.approx(0.12)
            for record in sections["full"]
        )
        == 2
    )
    assert (
        sum(
            record[0] == "C" and float(record[7]) == pytest.approx(0.06)
            for record in sections["full"]
        )
        == 32
    )
    assert not any(
        record[0] == "C" and float(record[7]) == pytest.approx(0.06)
        for record in sections["cylinders"]
    )
    flexible_backbones = [
        identity for identity in identities["full"]
        if identity.startswith("flex:flex-1:backbone:")
    ]
    assert len(flexible_backbones) == 32
    assert flexible_backbones[0].endswith(":near:0")
    assert flexible_backbones[-1].endswith(":near:1")


def test_unligated_crossover_gets_full_only_amber_warning_at_midpoint() -> None:
    crossover = SimpleNamespace(
        id="xo-open",
        half_a=SimpleNamespace(helix_id="h1", index=0, strand="FORWARD"),
        half_b=SimpleNamespace(helix_id="h2", index=0, strand="REVERSE"),
        extra_bases=None,
    )
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(
                id="s1",
                is_scaffold=False,
                color="#0066cc",
                sequence="AA",
                domains=[],
            )
        ],
        cluster_transforms=[],
        crossovers=[crossover],
        forced_ligations=[],
        overhang_bindings=[],
        duplexes=[],
        overhang_connections=[],
        flexible_connections=[],
    )
    nucleotides = [
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": helix_id,
            "bp_index": 0,
            "direction": direction,
            "backbone_position": [x, 0, 0],
        }
        for helix_id, direction, x in (
            ("h1", "FORWARD", 0),
            ("h2", "REVERSE", 2),
        )
    ]
    text = _serialize_scene(
        design,
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
        unligated_crossover_ids=["xo-open"],
    )
    sections = _scene_sections(text)

    warning_edges = [
        record
        for record in sections["full"]
        if record[0] == "C" and float(record[7]) == pytest.approx(0.12)
    ]
    warning_boxes = [
        record
        for record in sections["full"]
        if record[0] == "B"
        and np.allclose(
            [float(value) for value in record[13:16]], [245 / 255, 166 / 255, 35 / 255]
        )
    ]
    assert len(warning_edges) == 3
    assert len(warning_boxes) == 2
    assert not any(
        record[0] == "C" and float(record[7]) == pytest.approx(0.12)
        for record in sections["cylinders"]
    )
