"""Focused checks for the local native-OpenXR bridge."""

import gzip
import itertools
import json
from types import SimpleNamespace
from urllib.parse import quote

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import routes_vr
from backend.api.routes_vr import (
    VRFeedbackRequest,
    VRJobSnapshotRow,
    VRLaunchRequest,
    VRPlaneFeedbackRequest,
    VRToolPreflightFeedbackRequest,
    VRToolFeedbackRequest,
    VRCamera,
    _bundle_expanded_scene,
    _event_payload,
    _expanded_helix_offsets,
    _expanded_scene_inputs,
    _cluster_gizmo_handle_centers,
    _require_local,
    _runtime_timing,
    _selection_cluster,
    _selection_clusters,
    _serialize_scene,
    _validate_streamed_scene_manifests,
    _view_rotation,
    _viewer_command,
    _write_feedback,
    _write_job_snapshot,
    _write_plane_feedback,
    _write_preflight_feedback,
    _write_tool_feedback,
    _write_scene_snapshot,
)
from backend.core.vr_scene_contract import compare_scenes, parse_scene_contract


_BASE_COLORS_FOR_TEST = {
    "A": (0x44 / 255, 0xDD / 255, 0x88 / 255),
    "T": (1.0, 0x55 / 255, 0x55 / 255),
    "G": (1.0, 0xCC / 255, 0.0),
    "C": (0x55 / 255, 0xAA / 255, 1.0),
}


def _owner_token(*values) -> str:
    return quote(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")),
        safe="-_.!~*'()",
    )


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


def _semantic_atom_id(base_key: str, atom_name: str) -> str:
    payload = json.dumps(
        (base_key, atom_name), ensure_ascii=False, separators=(",", ":")
    )
    return quote(f"atom-ref:{payload}", safe="-_.:~")


def _semantic_atom_bond_id(first: tuple[str, str], second: tuple[str, str]) -> str:
    payload = json.dumps((first, second), ensure_ascii=False, separators=(",", ":"))
    return quote(f"atom-bond-ref:{payload}", safe="-_.:~")


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
            SimpleNamespace(
                id="left", axis_start=point(-1, 0, 0), axis_end=point(-1, 0, 10)
            ),
            SimpleNamespace(
                id="right", axis_start=point(1, 0, 0), axis_end=point(1, 0, 10)
            ),
        ],
        strands=[],
        extensions=[],
    )

    offsets = _expanded_helix_offsets(design)

    expected = 5.0 / 2.25 - 1.0
    np.testing.assert_allclose(offsets["left"], [-expected, 0, 0])
    np.testing.assert_allclose(offsets["right"], [expected, 0, 0])


def test_vr_owner_aliases_use_desktop_smallest_selectable_cluster_rule() -> None:
    large = SimpleNamespace(
        id="large",
        is_default=False,
        helix_ids=["h1", "h2"],
        domain_ids=[],
    )
    small = SimpleNamespace(
        id="small",
        is_default=False,
        helix_ids=["h1"],
        domain_ids=[],
    )
    default = SimpleNamespace(
        id="default",
        is_default=True,
        helix_ids=["h1", "h2", "h3"],
        domain_ids=[],
    )
    design = SimpleNamespace(strands=[], cluster_transforms=[large, default, small])

    assert _selection_cluster(design, {"helix_id": "h1"}).id == "small"
    assert [
        cluster.id for cluster in _selection_clusters(design, {"helix_id": "h1"})
    ] == ["small", "large", "default"]


def test_v9_cluster_handle_matches_desktop_mixed_cluster_visual_centroid() -> None:
    cluster = SimpleNamespace(
        id="cluster:a b",
        helix_ids=["bridge", "owned"],
        domain_ids=[SimpleNamespace(strand_id="s1", domain_index=0)],
    )
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(id="s1", domains=[SimpleNamespace(helix_id="bridge")])
        ],
        cluster_transforms=[cluster],
    )
    nucleotides = [
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": "bridge",
            "backbone_position": [1, 2, 3],
        },
        {
            "strand_id": "other",
            "domain_index": 0,
            "helix_id": "bridge",
            "backbone_position": [100, 100, 100],
        },
        {
            "strand_id": "s2",
            "domain_index": 0,
            "helix_id": "owned",
            "backbone_position": [3, 4, 5],
        },
    ]
    view_rotation = np.asarray([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float)

    records = _cluster_gizmo_handle_centers(design, nucleotides, view_rotation)

    assert records[0][0] == _owner_token("cluster", "cluster:a b")
    np.testing.assert_allclose(records[0][1], [4, 3, -2])


def test_expanded_scene_translates_owners_and_interpolates_crossover_atoms() -> None:
    point = lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)
    design = SimpleNamespace(
        helices=[
            SimpleNamespace(
                id="a", axis_start=point(-1, 0, 0), axis_end=point(-1, 0, 10)
            ),
            SimpleNamespace(
                id="b", axis_start=point(1, 0, 0), axis_end=point(1, 0, 10)
            ),
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


def test_expanded_offsets_match_desktop_axis_tie_priority() -> None:
    point = lambda x, y, z: SimpleNamespace(x=x, y=y, z=z)
    design = SimpleNamespace(helices=[
        SimpleNamespace(
            id="a", axis_start=point(0, 0, 0), axis_end=point(1, 1, 1)
        ),
        SimpleNamespace(
            id="b", axis_start=point(2, 0, 0), axis_end=point(3, 1, 1)
        ),
    ])

    offsets = _expanded_helix_offsets(design)

    assert offsets["a"][0] < 0
    assert offsets["b"][0] > 0
    assert offsets["a"][2] == offsets["b"][2] == 0


def test_v12_bundle_pairs_primitives_owners_handles_and_endpoint_scopes() -> None:
    natural = """NADOCVR 12 full strand
R full
K cluster-owner 0 0 0
J b base-owner base 0 0 0
D c cluster-owner
P owner 0 0 0 .1 1 1 1 1 1 1 1 1 1 1 1 1
A owner 1 b
T owner 1 c 1 1
W owner 2 c 1 1 b 1 1
"""
    expanded = natural.replace("P owner 0 0 0", "P owner 2 0 0").replace(
        "K cluster-owner 0 0 0", "K cluster-owner 1 0 0"
    )

    bundled = _bundle_expanded_scene(natural, expanded)

    assert bundled.startswith("NADOCVR 12 full strand\n")
    assert "R full\nK cluster-owner 0 0 0" in bundled
    assert "E full\nK cluster-owner 1 0 0" in bundled

    mismatched = expanded.replace("owner", "different")
    with pytest.raises(HTTPException, match="identities differ"):
        _bundle_expanded_scene(natural, mismatched)

    mismatched_alias = expanded.replace("A owner 1 b", "A owner 1 c")
    with pytest.raises(HTTPException, match="owner aliases differ"):
        _bundle_expanded_scene(natural, mismatched_alias)

    mismatched_handle = expanded.replace("cluster-owner", "different-handle", 1)
    with pytest.raises(HTTPException, match="cluster handles differ"):
        _bundle_expanded_scene(natural, mismatched_handle)

    mismatched_transform = expanded.replace(
        "T owner 1 c 1 1", "T owner 1 c 1 0"
    )
    with pytest.raises(HTTPException, match="transform owners differ"):
        _bundle_expanded_scene(natural, mismatched_transform)

    mismatched_tool_handle = expanded.replace(
        "J b base-owner base", "J b base-owner atom"
    )
    with pytest.raises(HTTPException, match="tool handles differ"):
        _bundle_expanded_scene(natural, mismatched_tool_handle)

    mismatched_scope_owner = expanded.replace(
        "W owner 2 c 1 1 b 1 1",
        "W owner 2 c 1 1 b 1 0",
    )
    with pytest.raises(HTTPException, match="tool-scope owners differ"):
        _bundle_expanded_scene(natural, mismatched_scope_owner)


def test_native_event_reader_is_bounded_and_tolerates_partial_writes(tmp_path) -> None:
    event_path = tmp_path / "vr-event.json"
    event_path.write_text(
        '{"sequence":7,"hover_identity":"nuc:s1:0:h1:4:FORWARD:0",'
        '"select_sequence":2,"select_identity":"nuc:s1:0:h1:3:FORWARD:0",'
        '"level_sequence":3,"selection_level":"domain",'
        '"tool_sequence":4,"tool_mode":"twist","tool_action":"preview",'
        '"tool_target_identity":"nuc:s1:0:h1:3:FORWARD:0",'
        '"tool_target_kind":"domain",'
        '"tool_target_owner_tokens":["domain-token"]}'
    )
    assert _event_payload({"event_path": str(event_path)}) == {
        "sequence": 7,
        "hover_identity": "nuc:s1:0:h1:4:FORWARD:0",
        "select_sequence": 2,
        "select_identity": "nuc:s1:0:h1:3:FORWARD:0",
        "level_sequence": 3,
        "selection_level": "domain",
        "tool_sequence": 4,
        "tool_mode": "twist",
        "tool_action": "preview",
        "tool_target_identity": "nuc:s1:0:h1:3:FORWARD:0",
        "tool_target_kind": "domain",
        "tool_target_owner_tokens": ["domain-token"],
        "tool_config_sequence": 0,
        "tool_config": None,
        "plane_pick_sequence": 0,
        "plane_pick_config_sequence": 0,
        "plane_pick_slot": None,
        "plane_pick_identity": None,
        "transform_sequence": 0,
        "transform_matrix": np.identity(4).flatten(order="F").tolist(),
        "ready_sequence": 0,
        "first_frame_at_ms": None,
        "first_frame_cpu_ms": None,
        "display_period_ms": None,
    }

    event_path.write_text(
        '{"sequence":8,"tool_sequence":5,"tool_mode":"delete","tool_action":"confirm"}'
    )
    assert _event_payload({"event_path": str(event_path)})["sequence"] == 0

    for invalid_target in (
        {
            "sequence": 9,
            "tool_target_identity": "nuc:s1",
            "tool_target_kind": "none",
            "tool_target_owner_tokens": [],
        },
        {
            "sequence": 9,
            "tool_target_identity": "nuc:s1",
            "tool_target_kind": "domain",
            "tool_target_owner_tokens": [],
        },
        {
            "sequence": 9,
            "tool_target_identity": "nuc:s1",
            "tool_target_kind": "domain",
            "tool_target_owner_tokens": ["not whitespace safe"],
        },
    ):
        event_path.write_text(json.dumps(invalid_target))
        assert _event_payload({"event_path": str(event_path)})["sequence"] == 0


def test_native_tool_transform_returns_to_nadoc_coordinates(tmp_path) -> None:
    event_path = tmp_path / "vr-transform.json"
    view_transform = np.identity(4)
    view_transform[:3, 3] = [1, 2, 3]
    event_path.write_text(
        json.dumps(
            {
                "sequence": 1,
                "transform_sequence": 2,
                "transform_matrix": view_transform.flatten(order="F").tolist(),
            }
        )
    )
    rotation = _view_rotation(
        VRCamera(position=[0, 0, 0], target=[1, 0, 0], up=[0, 1, 0])
    )

    payload = _event_payload(
        {"event_path": str(event_path), "view_rotation": rotation.tolist()}
    )
    transform = np.asarray(payload["transform_matrix"]).reshape((4, 4), order="F")

    assert payload["transform_sequence"] == 2
    np.testing.assert_allclose(transform[:3, 3], [-3, 2, 1])

    event_path.write_text('{"sequence":')
    assert _event_payload({"event_path": str(event_path)}) == {
        "sequence": 0,
        "hover_identity": None,
        "select_sequence": 0,
        "select_identity": None,
        "level_sequence": 0,
        "selection_level": "default",
        "tool_sequence": 0,
        "tool_mode": "inspect",
        "tool_action": "activate",
        "tool_target_identity": None,
        "tool_target_kind": "none",
        "tool_target_owner_tokens": [],
        "tool_config_sequence": 0,
        "tool_config": None,
        "plane_pick_sequence": 0,
        "plane_pick_config_sequence": 0,
        "plane_pick_slot": None,
        "plane_pick_identity": None,
        "transform_sequence": 0,
        "transform_matrix": np.identity(4).flatten(order="F").tolist(),
        "ready_sequence": 0,
        "first_frame_at_ms": None,
        "first_frame_cpu_ms": None,
        "display_period_ms": None,
    }

    event_path.write_text("x" * 4097)
    assert _event_payload({"event_path": str(event_path)})["sequence"] == 0


def test_native_tool_configuration_drafts_are_bounded_and_target_bound(
    tmp_path,
) -> None:
    event_path = tmp_path / "vr-tool-config.json"
    base = {
        "sequence": 4,
        "tool_config_sequence": 3,
        "tool_config": {
            "mode": "extrude",
            "target_identity": "nuc:s1:0:h1:3:FORWARD:0",
            "target_kind": "end",
            "target_owner_tokens": ["end-token"],
            "length_bp": 42,
            "direction_sign": -1,
            "strand_filter": "staples",
            "ligate_adjacent": False,
            "footprint_state": "unresolved",
        },
    }
    event_path.write_text(json.dumps(base))
    payload = _event_payload({"event_path": str(event_path)})
    assert payload["sequence"] == 4
    assert payload["tool_config_sequence"] == 3
    assert payload["tool_config"] == base["tool_config"]

    twist = {
        **base,
        "tool_config": {
            "mode": "twist",
            "target_identity": None,
            "target_kind": "none",
            "target_owner_tokens": [],
            "plane_a_bp": None,
            "plane_b_bp": None,
            "amount_mode": "total_degrees",
            "amount": 90,
        },
    }
    event_path.write_text(json.dumps(twist))
    assert _event_payload({"event_path": str(event_path)})["tool_config"] == {
        **twist["tool_config"],
        "amount": 90.0,
    }

    bend = {
        **base,
        "tool_config": {
            "mode": "bend",
            "target_identity": "cluster:c1",
            "target_kind": "cluster",
            "target_owner_tokens": ["cluster-token"],
            "plane_a_bp": -5,
            "plane_b_bp": 15,
            "angle_deg": 45,
            "direction_deg": 360,
        },
    }
    event_path.write_text(json.dumps(bend))
    assert _event_payload({"event_path": str(event_path)})["tool_config"] == {
        **bend["tool_config"],
        "angle_deg": 45.0,
        "direction_deg": 360.0,
    }

    invalid_configs = [
        {**base, "tool_config_sequence": 0},
        {**base, "tool_config": {**base["tool_config"], "length_bp": -1}},
        {**base, "tool_config": {**base["tool_config"], "length_bp": True}},
        {**base, "tool_config": {**base["tool_config"], "direction_sign": 0}},
        {**base, "tool_config": {**base["tool_config"], "footprint_state": "resolved"}},
        {**base, "tool_config_sequence": 1.5},
        {**twist, "tool_config": {**twist["tool_config"], "amount": float("nan")}},
        {**bend, "tool_config": {**bend["tool_config"], "direction_deg": 361}},
        {
            **bend,
            "tool_config": {
                **bend["tool_config"],
                "target_identity": None,
                "target_kind": "cluster",
            },
        },
    ]
    for invalid in invalid_configs:
        event_path.write_text(json.dumps(invalid))
        assert _event_payload({"event_path": str(event_path)})["sequence"] == 0

    event_path.write_text(json.dumps({
        "sequence": 5,
        "tool_config_sequence": 4,
        "tool_config": None,
    }))
    cleared = _event_payload({"event_path": str(event_path)})
    assert cleared["sequence"] == 5
    assert cleared["tool_config_sequence"] == 4
    assert cleared["tool_config"] is None


def test_native_deformation_plane_pick_events_are_bounded_and_config_bound(
    tmp_path,
) -> None:
    event_path = tmp_path / "vr-plane-pick.json"
    event = {
        "sequence": 7,
        "tool_config_sequence": 4,
        "tool_config": {
            "mode": "twist",
            "target_identity": "cluster:c1",
            "target_kind": "cluster",
            "target_owner_tokens": ["cluster-token"],
            "plane_a_bp": None,
            "plane_b_bp": None,
            "amount_mode": "total_degrees",
            "amount": 90,
        },
        "plane_pick_sequence": 3,
        "plane_pick_config_sequence": 4,
        "plane_pick_slot": "a",
        "plane_pick_identity": "nuc:s1:0:h1:12:FORWARD:0",
    }
    event_path.write_text(json.dumps(event))
    payload = _event_payload({"event_path": str(event_path)})
    assert payload["plane_pick_sequence"] == 3
    assert payload["plane_pick_config_sequence"] == 4
    assert payload["plane_pick_slot"] == "a"
    assert payload["plane_pick_identity"] == event["plane_pick_identity"]

    for update in (
        {"plane_pick_config_sequence": 3},
        {"plane_pick_sequence": True},
        {"plane_pick_slot": "x"},
        {"plane_pick_identity": "not whitespace safe"},
    ):
        event_path.write_text(json.dumps({**event, **update}))
        assert _event_payload({"event_path": str(event_path)})["sequence"] == 0


def test_native_first_frame_timing_is_bounded_and_uses_backend_milestones(
    tmp_path,
) -> None:
    event_path = tmp_path / "vr-timing.json"
    event_path.write_text(
        json.dumps(
            {
                "sequence": 1,
                "ready_sequence": 1,
                "first_frame_at_ms": 2_000_000.0,
                "first_frame_cpu_ms": 8.5,
                "display_period_ms": 11.111,
            }
        )
    )
    state = {
        "event_path": str(event_path),
        "browser_requested_at": 1997.8,
        "job_snapshot_ms": 180.0,
        "launch_requested_at": 1998.0,
        "snapshot_started_at": 1998.2,
        "snapshot_ready_at": 1999.0,
        "process_started_at": 1999.5,
    }
    event = _event_payload(state)
    assert event["ready_sequence"] == 1
    assert _runtime_timing(state, event) == {
        "first_frame_ready": True,
        "snapshot_ms": 800.0,
        "process_to_first_frame_ms": 500.0,
        "launch_to_first_frame_ms": 2000.0,
        "click_to_first_frame_ms": 2200.0,
        "job_snapshot_ms": 180.0,
        "first_frame_cpu_ms": 8.5,
        "display_period_ms": 11.111,
    }

    event_path.write_text(
        '{"sequence":2,"ready_sequence":1,"first_frame_at_ms":NaN,'
        '"first_frame_cpu_ms":8.5,"display_period_ms":11.111}'
    )
    assert _event_payload(state)["sequence"] == 0


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
            owner_tokens=["exact", "domain", "strand"],
            selection_kind="base",
        ),
    )
    assert feedback_path.read_text() == (
        "NADOCVR_FEEDBACK 3 4 1 1 base base nuc:s1:0:h1:3:FORWARD:0 "
        "3 exact domain strand\n"
    )
    assert feedback_path.stat().st_mode & 0o777 == 0o600
    assert not feedback_path.with_name(f"{feedback_path.name}.next").exists()

    with pytest.raises(HTTPException, match="Invalid VR feedback identity"):
        _write_feedback(
            {"feedback_path": str(feedback_path)},
            VRFeedbackRequest(select_sequence=5, identity="not whitespace safe"),
        )
    with pytest.raises(HTTPException, match="Invalid VR feedback identity"):
        _write_feedback(
            {"feedback_path": str(feedback_path)},
            VRFeedbackRequest(
                select_sequence=6,
                selected=True,
                owner_tokens=["not whitespace safe"],
            ),
        )


def test_native_tool_feedback_rotates_exact_locator_and_fails_closed(tmp_path) -> None:
    tool_feedback_path = tmp_path / "vr-tool-feedback.txt"
    tool_feedback_path.write_text(
        "NADOCVR_TOOL_FEEDBACK 2 0 0 0 0 0 unresolved none -\n"
    )
    rotation = _view_rotation(
        VRCamera(position=[0, 0, 0], target=[1, 0, 0], up=[0, 1, 0])
    )
    state = {
        "tool_feedback_path": str(tool_feedback_path),
        "view_rotation": rotation.tolist(),
    }
    _write_tool_feedback(
        state,
        VRToolFeedbackRequest(
            tool_config_sequence=7,
            target_identity="nuc:s1:0:h1:3:FORWARD:0",
            target_kind="end",
            resolved=True,
            reason="resolved",
            face_position=[1, 2, 3],
            face_normal=[1, 0, 0],
            preview_origin=[2, 3, 4],
            expanded_face_position=[5, 6, 7],
            expanded_face_normal=[0, 1, 0],
            expanded_preview_origin=[6, 7, 8],
            occupied=True,
            deformed=False,
            footprint_resolved=True,
        ),
    )
    fields = tool_feedback_path.read_text().split()
    assert fields[:10] == [
        "NADOCVR_TOOL_FEEDBACK", "3", "7", "1", "1", "0", "1", "resolved",
        "end", "nuc:s1:0:h1:3:FORWARD:0",
    ]
    np.testing.assert_allclose([float(value) for value in fields[10:13]], [3, 2, -1])
    np.testing.assert_allclose([float(value) for value in fields[13:16]], [0, 0, -1])
    np.testing.assert_allclose([float(value) for value in fields[16:19]], [4, 3, -2])
    np.testing.assert_allclose([float(value) for value in fields[19:22]], [7, 6, -5])
    np.testing.assert_allclose([float(value) for value in fields[22:25]], [0, 1, 0])
    np.testing.assert_allclose([float(value) for value in fields[25:]], [8, 7, -6])
    assert tool_feedback_path.stat().st_mode & 0o777 == 0o600

    _write_tool_feedback(
        state,
        VRToolFeedbackRequest(
            tool_config_sequence=8,
            target_identity="nuc:s1:0:h1:3:FORWARD:0",
            target_kind="end",
            resolved=False,
            reason="no_continuation_face",
        ),
    )
    assert tool_feedback_path.read_text() == (
        "NADOCVR_TOOL_FEEDBACK 3 8 0 0 0 0 no_continuation_face end "
        "nuc:s1:0:h1:3:FORWARD:0\n"
    )

    invalid = [
        dict(resolved=True, reason="resolved", face_position=None, face_normal=None),
        dict(
            resolved=True, reason="resolved", face_position=[0, 0, 0],
            face_normal=[0, 0, 0],
        ),
        dict(
            resolved=True,
            reason="resolved",
            face_position=[0, 0, 0],
            face_normal=[0, 0, 1],
            footprint_resolved=True,
            preview_origin=None,
        ),
        dict(
            resolved=False, reason="resolved", face_position=None, face_normal=None,
        ),
        dict(
            resolved=False,
            reason="no_continuation_face",
            face_position=None,
            face_normal=None,
            footprint_resolved=True,
        ),
    ]
    for values in invalid:
        with pytest.raises(HTTPException, match="Invalid VR tool feedback"):
            _write_tool_feedback(
                state,
                VRToolFeedbackRequest(
                    tool_config_sequence=9,
                    target_identity="nuc:s1:0:h1:3:FORWARD:0",
                    target_kind="end",
                    **values,
                ),
            )


def test_native_plane_feedback_is_private_target_bound_and_fail_closed(tmp_path) -> None:
    tool_feedback_path = tmp_path / "vr-tool-feedback.txt"
    state = {
        "plane_feedback_path": str(tool_feedback_path),
        "view_rotation": [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
    }
    _write_plane_feedback(
        state,
        VRPlaneFeedbackRequest(
            plane_pick_sequence=5,
            tool_config_sequence=7,
            target_identity="cluster:c1",
            target_kind="cluster",
            picked_identity="nuc:s1:0:h1:12:FORWARD:0",
            plane_slot="a",
            resolved=True,
            reason="resolved",
            plane_bp=12,
            plane_center=[1, 2, 3],
            plane_normal=[0, 0, 2],
            plane_half_extent_nm=8,
            expanded_plane_center=[4, 5, 6],
            expanded_plane_normal=[0, 2, 0],
            expanded_plane_half_extent_nm=8,
        ),
    )
    assert tool_feedback_path.read_text() == (
        "NADOCVR_PLANE_FEEDBACK 3 5 7 1 resolved a cluster cluster:c1 "
        "nuc:s1:0:h1:12:FORWARD:0 12 -2 1 3 0 0 1 8 "
        "-5 4 6 -1 0 0 8\n"
    )
    assert tool_feedback_path.stat().st_mode & 0o777 == 0o600
    assert not tool_feedback_path.with_name(f"{tool_feedback_path.name}.next").exists()

    invalid = [
        dict(resolved=False, reason="resolved", plane_bp=None),
        dict(resolved=True, reason="resolved", plane_bp=None),
        dict(resolved=False, reason="ambiguous_primitive", plane_bp=12),
        dict(
            resolved=True, reason="resolved", plane_bp=12,
            plane_center=[0, 0, 0], plane_normal=[0, 0, 0],
            plane_half_extent_nm=8,
            expanded_plane_center=[1, 0, 0], expanded_plane_normal=[0, 0, 1],
            expanded_plane_half_extent_nm=8,
        ),
        dict(
            resolved=True, reason="resolved", plane_bp=12,
            plane_center=[float("nan"), 0, 0], plane_normal=[0, 0, 1],
            plane_half_extent_nm=8,
            expanded_plane_center=[1, 0, 0], expanded_plane_normal=[0, 0, 1],
            expanded_plane_half_extent_nm=8,
        ),
        dict(
            resolved=True, reason="resolved", plane_bp=12,
            plane_center=[0, 0, 0], plane_normal=[0, 0, 1],
            plane_half_extent_nm=8,
            expanded_plane_center=[1, 0, 0], expanded_plane_normal=[0, 0, 0],
            expanded_plane_half_extent_nm=8,
        ),
    ]
    for values in invalid:
        with pytest.raises(HTTPException, match="Invalid VR deformation plane feedback"):
            _write_plane_feedback(
                state,
                VRPlaneFeedbackRequest(
                    plane_pick_sequence=6,
                    tool_config_sequence=7,
                    target_identity="cluster:c1",
                    target_kind="cluster",
                    picked_identity="bond:x",
                    plane_slot="b",
                    **values,
                ),
            )


def test_native_tool_preflight_feedback_is_private_target_bound_and_strict(
    tmp_path,
) -> None:
    feedback_path = tmp_path / "vr-preflight-feedback.txt"
    state = {"preflight_feedback_path": str(feedback_path)}
    _write_preflight_feedback(
        state,
        VRToolPreflightFeedbackRequest(
            preflight_sequence=1,
            tool_config_sequence=12,
            target_identity="nuc:end",
            target_kind="end",
            tool_mode="extrude",
            status="block",
            reason="backend_block",
        ),
    )
    assert feedback_path.read_text() == (
        "NADOCVR_PREFLIGHT 2 12 1 block extrude end nuc:end backend_block\n"
    )
    assert feedback_path.stat().st_mode & 0o777 == 0o600
    assert not feedback_path.with_name(f"{feedback_path.name}.next").exists()

    _write_preflight_feedback(
        state,
        VRToolPreflightFeedbackRequest(
            preflight_sequence=3,
            tool_config_sequence=13,
            target_identity=None,
            target_kind="none",
            tool_mode="bend",
            status="block",
            reason="stale_target",
        ),
    )
    assert feedback_path.read_text() == (
        "NADOCVR_PREFLIGHT 2 13 3 block bend none - stale_target\n"
    )

    assert _write_preflight_feedback(
        state,
        VRToolPreflightFeedbackRequest(
            preflight_sequence=2,
            tool_config_sequence=12,
            target_identity="nuc:end",
            target_kind="end",
            tool_mode="extrude",
            status="waiting",
            reason="design_changed",
        ),
    ) == (False, 3)
    assert feedback_path.read_text() == (
        "NADOCVR_PREFLIGHT 2 13 3 block bend none - stale_target\n"
    )

    assert _write_preflight_feedback(
        state,
        VRToolPreflightFeedbackRequest(
            preflight_sequence=3,
            tool_config_sequence=13,
            target_identity=None,
            target_kind="none",
            tool_mode="bend",
            status="waiting",
            reason="geometry_changed",
        ),
    ) == (False, 3)

    with pytest.raises(HTTPException, match="Invalid VR tool preflight feedback"):
        _write_preflight_feedback(
            state,
            VRToolPreflightFeedbackRequest(
                preflight_sequence=4,
                tool_config_sequence=14,
                target_identity="cluster:c1",
                target_kind="cluster",
                tool_mode="extrude",
                status="ok",
                reason="validated",
            ),
        )


def test_native_tool_preflight_feedback_converges_under_every_arrival_order(
    tmp_path,
) -> None:
    messages = [
        VRToolPreflightFeedbackRequest(
            preflight_sequence=1,
            tool_config_sequence=20,
            target_identity="nuc:end",
            target_kind="end",
            tool_mode="extrude",
            status="waiting",
            reason="design_changed",
        ),
        VRToolPreflightFeedbackRequest(
            preflight_sequence=2,
            tool_config_sequence=20,
            target_identity="nuc:end",
            target_kind="end",
            tool_mode="extrude",
            status="block",
            reason="backend_block",
        ),
        VRToolPreflightFeedbackRequest(
            preflight_sequence=3,
            tool_config_sequence=20,
            target_identity="nuc:end",
            target_kind="end",
            tool_mode="extrude",
            status="ok",
            reason="validated",
        ),
    ]
    for index, order in enumerate(itertools.permutations(messages)):
        feedback_path = tmp_path / f"vr-preflight-order-{index}.txt"
        state = {"preflight_feedback_path": str(feedback_path)}
        for message in order:
            _write_preflight_feedback(state, message)
        assert feedback_path.read_text() == (
            "NADOCVR_PREFLIGHT 2 20 3 ok extrude end nuc:end validated\n"
        )


def test_native_launch_passes_initial_selection_as_opaque_arguments(tmp_path) -> None:
    token = _owner_token("domain", "strand:a b", 2)
    command = _viewer_command(
        tmp_path / "scene.nadocvr",
        tmp_path / "event.json",
        tmp_path / "feedback.txt",
        tmp_path / "tool-feedback.txt",
        tmp_path / "plane-feedback.txt",
        tmp_path / "preflight-feedback.txt",
        tmp_path / "jobs.txt",
        VRLaunchRequest(
            selection_level="domain",
            selected_owner_tokens=[token],
            selected_selection_kind="domain",
        ),
    )
    assert command[-4:] == ["--selected-owner", token, "--selected-kind", "domain"]
    assert command[command.index("--selection-level") + 1] == "domain"
    assert command[command.index("--tool-feedback") + 1].endswith("tool-feedback.txt")
    assert command[command.index("--plane-feedback") + 1].endswith("plane-feedback.txt")
    assert command[command.index("--preflight-feedback") + 1].endswith(
        "preflight-feedback.txt"
    )
    assert command[command.index("--jobs") + 1].endswith("jobs.txt")

    with pytest.raises(HTTPException, match="initial VR selection"):
        routes_vr.launch_vr(
            VRLaunchRequest(
                selected_owner_tokens=["not whitespace safe"],
                selected_selection_kind="domain",
            ),
            _request("127.0.0.1", "http://localhost:5173"),
        )

    with pytest.raises(HTTPException, match="Invalid VR job snapshot"):
        routes_vr.launch_vr(
            VRLaunchRequest(
                jobs_snapshot_available=False,
                jobs=[
                    VRJobSnapshotRow(
                        job_id="run",
                        engine="cando",
                        status="completed",
                        label="Run",
                        status_text="CanDo - completed - 100.0%",
                        depth=0,
                        progress_permille=1000,
                    )
                ],
            ),
            _request("127.0.0.1", "http://localhost:5173"),
        )


def test_native_job_snapshot_is_private_bounded_and_url_safe() -> None:
    rows = [
        VRJobSnapshotRow(
            job_id="run 17/alpha",
            parent_job_id=None,
            engine="namd",
            status="running",
            label="Production run 17",
            status_text="NAMD - running - 42.5%",
            depth=0,
            progress_permille=425,
            viewable=True,
            stale=True,
            archived=False,
        )
    ]
    path = _write_job_snapshot(rows)
    try:
        lines = path.read_text().splitlines()
        assert lines == [
            "NADOCVR_JOBS 1 1 1 1",
            "J 0 425 1 1 0 namd running run%2017%2Falpha - "
            "Production%20run%2017 NAMD%20-%20running%20-%2042.5%25",
        ]
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        path.unlink(missing_ok=True)

    unavailable = _write_job_snapshot([], available=False)
    try:
        assert unavailable.read_text() == "NADOCVR_JOBS 1 0 0 0\n"
    finally:
        unavailable.unlink(missing_ok=True)


def test_scene_snapshot_writer_is_private_gzip_and_round_trips() -> None:
    scene = "NADOCVR 12 full strand\nR full\n" + ("# repeated payload\n" * 5000)
    path = _write_scene_snapshot(scene)
    try:
        assert path.suffixes[-2:] == [".nadocvr", ".gz"]
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_size < len(scene.encode()) / 10
        with gzip.open(path, mode="rt", encoding="utf-8") as compressed:
            assert compressed.read() == scene
    finally:
        path.unlink(missing_ok=True)

    def produce(write_line) -> None:
        for line in scene.splitlines():
            write_line(line)

    streamed = _write_scene_snapshot(producer=produce)
    try:
        with gzip.open(streamed, mode="rt", encoding="utf-8") as compressed:
            assert compressed.read() == scene
    finally:
        streamed.unlink(missing_ok=True)


def test_streamed_manifest_detects_pose_contract_drift() -> None:
    natural = {"full": {"primitive": (2, "same"), "A": (1, "owners")}}
    _validate_streamed_scene_manifests(natural, natural)
    with pytest.raises(HTTPException, match="primitive identities differ in full"):
        _validate_streamed_scene_manifests(
            natural,
            {"full": {"primitive": (3, "different"), "A": (1, "owners")}},
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


def test_build_environment_keeps_sbin_on_path_but_drops_conda() -> None:
    """Regression test: the sanitized launch environment has two competing jobs.

    It must drop conda/Miniforge's LD_LIBRARY_PATH (which shadows SteamVR's own
    bundled Qt5 and breaks vrmonitor), while still exposing /usr/sbin, because
    SteamVR's vrsetup.sh shells out to `getcap` there. A PATH without sbin makes
    setup "fail" and raises a BLOCKING zenity dialog that stalls every launch.
    """
    env = routes_vr._build_environment()
    path_entries = env["PATH"].split(":")
    assert "/usr/sbin" in path_entries
    assert "/sbin" in path_entries
    assert "/usr/bin" in path_entries
    for leaked in ("LD_LIBRARY_PATH", "CONDA_PREFIX", "CMAKE_PREFIX_PATH"):
        assert leaked not in env


def test_start_steamvr_is_noop_when_runtime_and_dashboard_are_ready(
    monkeypatch,
) -> None:
    ready = {"steamvr_running": True, "dashboard_running": True}
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: ready)
    monkeypatch.setattr(routes_vr, "_detach_hmd_from_desktop", lambda: None)

    def unexpected_spawn(*_args, **_kwargs):
        raise AssertionError("Steam must not be spawned for an already-ready runtime")

    monkeypatch.setattr(routes_vr.subprocess, "Popen", unexpected_spawn)
    assert routes_vr._start_steamvr() == ready


def test_start_steamvr_launches_steam_with_sanitized_environment(
    monkeypatch, tmp_path
) -> None:
    """Regression test: launching Steam with the raw dev-shell environment leaks
    conda/Miniforge's LD_LIBRARY_PATH into SteamVR's whole process tree, which
    breaks vrmonitor's ability to find its own bundled Qt5 libs (observed:
    'vrmonitor: error while loading shared libraries: libQt5OpenGL.so.5'), so
    Steam must launch with the same sanitized environment as the native viewer."""
    not_ready = {"steamvr_running": False, "dashboard_running": False}
    ready = {"steamvr_running": True, "dashboard_running": True}
    payloads = iter([not_ready, ready])
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: next(payloads))
    monkeypatch.setattr(routes_vr, "_detach_hmd_from_desktop", lambda: None)
    monkeypatch.setattr(routes_vr.Path, "is_file", lambda self: True)
    monkeypatch.setattr(
        routes_vr, "_STEAMVR_LOG_PATH", tmp_path / "steamvr.log"
    )
    sentinel_env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    monkeypatch.setattr(routes_vr, "_build_environment", lambda: dict(sentinel_env))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/home/jojo/miniforge3/lib.AVX2_256")

    captured: dict = {}

    def fake_popen(*_args, **kwargs):
        captured["env"] = kwargs["env"]
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(routes_vr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(routes_vr.time, "sleep", lambda _seconds: None)

    assert routes_vr._start_steamvr() == ready
    assert captured["env"] == sentinel_env
    assert "LD_LIBRARY_PATH" not in captured["env"]


def test_start_steamvr_detaches_hmd_even_when_already_ready(monkeypatch) -> None:
    """Regression test: process-name readiness doesn't prove direct mode ever
    succeeded, so the HMD must be detached on every call, not only fresh launches."""
    ready = {"steamvr_running": True, "dashboard_running": True}
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: ready)
    calls: list[None] = []
    monkeypatch.setattr(
        routes_vr, "_detach_hmd_from_desktop", lambda: calls.append(None)
    )

    def unexpected_spawn(*_args, **_kwargs):
        raise AssertionError("Steam must not be spawned for an already-ready runtime")

    monkeypatch.setattr(routes_vr.subprocess, "Popen", unexpected_spawn)
    assert routes_vr._start_steamvr() == ready
    assert calls == [None]


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
            name="C1'",
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
            name="O3'",
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

    assert text.startswith("NADOCVR 12 full strand\n")
    assert set(sections) == {"full", "cylinders", "ballstick", "stick"}
    assert all(len(values) == len(set(values)) for values in identities.values())
    assert "nuc:s1:0:h1:1:FORWARD:0:backbone" in identities["full"]
    assert _semantic_atom_id("h1:0:FORWARD", "C1'") in identities["ballstick"]
    assert (
        _semantic_atom_bond_id(("h1:0:FORWARD", "C1'"), ("h1:1:FORWARD", "O3'"))
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

    reversed_bond_text = _serialize_scene(
        design,
        nucleotides,
        [{"helix_id": "h1", "start": [0, 0, 0], "end": [0, 0, 1]}],
        camera,
        atomistic_model=SimpleNamespace(atoms=atoms, bonds=[(1, 0)]),
    )
    assert compare_scenes(text, reversed_bond_text).ok
    streamed_lines = []
    manifest = _serialize_scene(
        design,
        nucleotides,
        [{"helix_id": "h1", "start": [0, 0, 0], "end": [0, 0, 1]}],
        camera,
        atomistic_model=SimpleNamespace(atoms=atoms, bonds=[(0, 1)]),
        line_writer=streamed_lines.append,
    )
    assert "\n".join(streamed_lines) + "\n" == text
    assert set(manifest) == {"full", "cylinders", "ballstick", "stick"}


def test_v11_atom_identity_rejects_missing_or_duplicate_chemical_names() -> None:
    atom = SimpleNamespace(
        name="P",
        x=0.0,
        y=0.0,
        z=0.0,
        strand_id="s1",
        helix_id="h1",
        bp_index=0,
        direction="FORWARD",
        residue="DA",
        element="P",
    )
    with pytest.raises(HTTPException, match="Duplicate semantic VR atom identity"):
        _serialize_scene(
            SimpleNamespace(strands=[], cluster_transforms=[]),
            [],
            [],
            atomistic_model=SimpleNamespace(atoms=[atom, atom], bonds=[]),
        )
    with pytest.raises(HTTPException, match="missing its name"):
        _serialize_scene(
            SimpleNamespace(strands=[], cluster_transforms=[]),
            [],
            [],
            atomistic_model=SimpleNamespace(
                atoms=[SimpleNamespace(**{**vars(atom), "name": ""})], bonds=[]
            ),
        )


def test_v12_generalized_handles_and_tool_scopes_bridge_representations() -> None:
    strand_id = "strand: one"
    helix_id = "helix: one"
    cluster_id = "cluster one"
    domain = SimpleNamespace(
        helix_id=helix_id,
        start_bp=0,
        end_bp=0,
        direction="FORWARD",
    )
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(
                id=strand_id,
                is_scaffold=False,
                color="#3366cc",
                sequence="A",
                domains=[domain],
            )
        ],
        cluster_transforms=[
            SimpleNamespace(
                id=cluster_id,
                domain_ids=[SimpleNamespace(strand_id=strand_id, domain_index=0)],
                helix_ids=[helix_id],
                auto_created=False,
                color=None,
                is_default=False,
            ),
            SimpleNamespace(
                id="larger cluster",
                domain_ids=[],
                helix_ids=[helix_id, "other helix"],
                auto_created=False,
                color=None,
                is_default=False,
            ),
        ],
    )
    nucleotide = {
        "strand_id": strand_id,
        "domain_index": 0,
        "helix_id": helix_id,
        "bp_index": 0,
        "direction": "FORWARD",
        "is_five_prime": True,
        "backbone_position": [0, 0, 0],
        "base_position": [0.2, 0, 0],
        "base_normal": [1, 0, 0],
        "axis_tangent": [0, 0, 1],
    }
    atom = SimpleNamespace(
        name="C1'",
        x=0.0,
        y=0.0,
        z=0.0,
        strand_id=strand_id,
        helix_id=helix_id,
        bp_index=0,
        direction="FORWARD",
        residue="DA",
        element="C",
    )
    text = _serialize_scene(
        design,
        [nucleotide],
        [
            {
                "helix_id": helix_id,
                "segments": [
                    {
                        "start": [0, 0, -0.5],
                        "end": [0, 0, 0.5],
                        "strand_id": strand_id,
                        "domain_index": 0,
                        "bp_lo": 0,
                        "bp_hi": 0,
                    }
                ],
            }
        ],
        atomistic_model=SimpleNamespace(atoms=[atom], bonds=[]),
    )
    scene = parse_scene_contract(text)
    full_backbone = next(
        primitive
        for primitive in scene["full"].values()
        if primitive.identity.endswith(":backbone")
    )
    atom_sphere = next(
        primitive
        for primitive in scene["ballstick"].values()
        if primitive.record_type == "P"
    )
    coarse_domain = next(
        primitive
        for primitive in scene["cylinders"].values()
        if primitive.identity.endswith(":coarse")
    )
    base = _owner_token("base", f"{helix_id}:0:FORWARD")
    end = _owner_token("end", f"{helix_id}:0:FORWARD")
    domain_owner = _owner_token("domain", strand_id, 0)
    strand_owner = _owner_token("strand", strand_id)
    cluster_owner = _owner_token("cluster", cluster_id)
    larger_cluster_owner = _owner_token("cluster", "larger cluster")
    atom_owner = _owner_token("atom", f"{helix_id}:0:FORWARD", "C1'")
    cluster_handle = scene["full"][cluster_owner]
    assert cluster_handle.record_type == "K"
    np.testing.assert_allclose(cluster_handle.values, [0, 0, 0])

    assert full_backbone.owner_aliases == (
        base,
        end,
        domain_owner,
        strand_owner,
        cluster_owner,
        larger_cluster_owner,
    )
    assert set(atom_sphere.owner_aliases) >= {
        base,
        domain_owner,
        strand_owner,
        cluster_owner,
        larger_cluster_owner,
    }
    assert coarse_domain.owner_aliases == (
        domain_owner,
        strand_owner,
        cluster_owner,
        larger_cluster_owner,
    )
    assert scene["full"][larger_cluster_owner].record_type == "K"
    assert scene["full"][base].tool_scope_kind == "base"
    assert scene["full"][end].tool_scope_kind == "end"
    assert scene["full"][domain_owner].tool_scope_kind == "domain"
    assert scene["full"][strand_owner].tool_scope_kind == "strand"
    assert scene["ballstick"][atom_owner].tool_scope_kind == "atom"
    assert full_backbone.transform_owners == (
        (cluster_owner, 1.0, 1.0),
        (larger_cluster_owner, 1.0, 1.0),
    )
    assert atom_sphere.transform_owners == full_backbone.transform_owners
    assert coarse_domain.transform_owners == full_backbone.transform_owners
    assert full_backbone.tool_scope_owners == (
        (base, 1.0, 1.0),
        (end, 1.0, 1.0),
        (domain_owner, 1.0, 1.0),
        (strand_owner, 1.0, 1.0),
        (cluster_owner, 1.0, 1.0),
        (larger_cluster_owner, 1.0, 1.0),
    )
    assert atom_sphere.tool_scope_owners == (
        *full_backbone.tool_scope_owners,
        (atom_owner, 1.0, 1.0),
    )
    assert coarse_domain.tool_scope_owners == (
        (domain_owner, 1.0, 1.0),
        (strand_owner, 1.0, 1.0),
        (cluster_owner, 1.0, 1.0),
        (larger_cluster_owner, 1.0, 1.0),
    )


def test_v12_boundary_connections_assign_every_tool_scope_per_endpoint() -> None:
    strands = [
        SimpleNamespace(
            id=f"s{index}",
            is_scaffold=index == 1,
            color=None,
            sequence="A",
            domains=[
                SimpleNamespace(
                    helix_id=f"h{index}", start_bp=0, end_bp=0, direction="FORWARD"
                )
            ],
        )
        for index in (1, 2)
    ]
    clusters = [
        SimpleNamespace(
            id=f"c{index}",
            domain_ids=[SimpleNamespace(strand_id=f"s{index}", domain_index=0)],
            helix_ids=[f"h{index}"],
            auto_created=False,
            color=None,
            is_default=False,
        )
        for index in (1, 2)
    ]
    crossover = SimpleNamespace(
        id="boundary",
        half_a=SimpleNamespace(helix_id="h1", index=0, strand="FORWARD"),
        half_b=SimpleNamespace(helix_id="h2", index=0, strand="FORWARD"),
        extra_bases=None,
    )
    design = SimpleNamespace(
        strands=strands,
        cluster_transforms=clusters,
        crossovers=[crossover],
        forced_ligations=[],
        overhang_bindings=[],
        duplexes=[],
        overhang_connections=[],
        flexible_connections=[],
    )
    nucleotides = [
        {
            "strand_id": f"s{index}",
            "domain_index": 0,
            "helix_id": f"h{index}",
            "bp_index": 0,
            "direction": "FORWARD",
            "backbone_position": [float(index - 1), 0, 0],
        }
        for index in (1, 2)
    ]
    atoms = [
        SimpleNamespace(
            name="C1'" if index == 1 else "O3'",
            x=float(index - 1),
            y=0.0,
            z=0.0,
            strand_id=f"s{index}",
            helix_id=f"h{index}",
            bp_index=0,
            direction="FORWARD",
            residue="DA",
            element="C",
        )
        for index in (1, 2)
    ]
    scene = parse_scene_contract(
        _serialize_scene(
            design,
            nucleotides,
            [],
            atomistic_model=SimpleNamespace(atoms=atoms, bonds=[(0, 1)]),
        )
    )
    direct = next(
        primitive
        for primitive in scene["full"].values()
        if primitive.identity == "crossover:boundary:direct"
    )
    atom_bond = next(
        primitive
        for primitive in scene["ballstick"].values()
        if primitive.identity.startswith("atom-bond-ref:")
    )
    expected = (
        (_owner_token("cluster", "c1"), 1.0, 0.0),
        (_owner_token("cluster", "c2"), 0.0, 1.0),
    )
    assert direct.transform_owners == expected
    assert atom_bond.transform_owners == expected
    direct_scopes = {
        token: (start, end)
        for token, start, end in direct.tool_scope_owners
    }
    atom_scopes = {
        token: (start, end)
        for token, start, end in atom_bond.tool_scope_owners
    }
    for kind, values, weights in (
        ("base", ("h1:0:FORWARD",), (1.0, 0.0)),
        ("domain", ("s1", 0), (1.0, 0.0)),
        ("strand", ("s1",), (1.0, 0.0)),
        ("cluster", ("c1",), (1.0, 0.0)),
        ("base", ("h2:0:FORWARD",), (0.0, 1.0)),
        ("domain", ("s2", 0), (0.0, 1.0)),
        ("strand", ("s2",), (0.0, 1.0)),
        ("cluster", ("c2",), (0.0, 1.0)),
    ):
        token = _owner_token(kind, *values)
        assert direct_scopes[token] == weights
        assert atom_scopes[token] == weights
    assert atom_scopes[_owner_token("atom", "h1:0:FORWARD", "C1'")] == (
        1.0,
        0.0,
    )
    assert atom_scopes[_owner_token("atom", "h2:0:FORWARD", "O3'")] == (
        0.0,
        1.0,
    )


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


def test_reverse_loop_insertions_thread_backbone_in_desktop_copy_order() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(
                id="reverse",
                is_scaffold=False,
                color="#ff6b6b",
                sequence="ATCG",
            )
        ],
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
    )

    def nucleotide(bp_index: int, z: float) -> dict:
        return {
            "strand_id": "reverse",
            "domain_index": 0,
            "helix_id": "h0",
            "bp_index": bp_index,
            "direction": "REVERSE",
            "backbone_position": [0, 0, z],
        }

    # Geometry emits loop copies in ascending axial/copy order for both strand
    # directions. Desktop visits a reverse strand's copies 1 -> 0 so its 5'->3'
    # backbone remains monotone rather than dipping into and back out of the loop.
    natural_nucleotides = [
        nucleotide(6, 2.00),
        nucleotide(5, 1.50),
        nucleotide(5, 1.84),
        nucleotide(4, 1.34),
    ]
    expanded_nucleotides = [
        {**item, "backbone_position": [5, 0, item["backbone_position"][2]]}
        for item in natural_nucleotides
    ]
    kwargs = {"atomistic_model": SimpleNamespace(atoms=[], bonds=[])}
    natural = _serialize_scene(design, natural_nucleotides, [], **kwargs)
    expanded = _serialize_scene(design, expanded_nucleotides, [], **kwargs)
    scene = parse_scene_contract(_bundle_expanded_scene(natural, expanded))

    expected = [
        "backbone:nuc:reverse:0:h0:6:REVERSE:0~nuc:reverse:0:h0:5:REVERSE:1",
        "backbone:nuc:reverse:0:h0:5:REVERSE:1~nuc:reverse:0:h0:5:REVERSE:0",
        "backbone:nuc:reverse:0:h0:5:REVERSE:0~nuc:reverse:0:h0:4:REVERSE:0",
    ]
    for pose in ("full", "expanded/full"):
        connectors = [
            primitive
            for primitive in scene[pose].values()
            if primitive.identity.startswith("backbone:")
        ]
        assert [primitive.identity for primitive in connectors] == expected
        z_path = [connectors[0].values[2], *[item.values[5] for item in connectors]]
        assert z_path == pytest.approx([2.00, 1.84, 1.50, 1.34])

    natural_points = {
        primitive.identity: primitive
        for primitive in scene["full"].values()
        if primitive.record_type == "P"
    }
    expected_base_colors = {
        "nuc:reverse:0:h0:6:REVERSE:0:backbone": _BASE_COLORS_FOR_TEST["A"],
        "nuc:reverse:0:h0:5:REVERSE:1:backbone": _BASE_COLORS_FOR_TEST["T"],
        "nuc:reverse:0:h0:5:REVERSE:0:backbone": _BASE_COLORS_FOR_TEST["C"],
        "nuc:reverse:0:h0:4:REVERSE:0:backbone": _BASE_COLORS_FOR_TEST["G"],
    }
    for identity, color in expected_base_colors.items():
        assert natural_points[identity].values[7:10] == pytest.approx(color)


def test_base_coloring_keeps_extensions_and_overhang_fallback_semantic() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(
                id="core", is_scaffold=False, color="#ff6b6b", sequence="CG"
            ),
            SimpleNamespace(
                id="overhang", is_scaffold=False, color="#ffd93d", sequence=None
            ),
        ],
        extensions=[],
        overhangs=[
            SimpleNamespace(
                id="oh",
                sequence="AT",
                sub_domains=[
                    SimpleNamespace(
                        start_bp_offset=0,
                        length_bp=1,
                        sequence_override="G",
                    ),
                    SimpleNamespace(
                        start_bp_offset=1,
                        length_bp=1,
                        sequence_override="C",
                    ),
                ],
            )
        ],
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
    )

    def nucleotide(
        strand_id: str,
        helix_id: str,
        bp_index: int,
        x: float,
        **extra,
    ) -> dict:
        return {
            "strand_id": strand_id,
            "domain_index": 0,
            "helix_id": helix_id,
            "bp_index": bp_index,
            "direction": "FORWARD",
            "backbone_position": [x, 0, 0],
            **extra,
        }

    nucleotides = [
        nucleotide("core", "h", 0, 0),
        nucleotide("core", "h", 1, 0.34),
        # A 5′ AC extension is emitted root -> tip as C, A.
        nucleotide(
            "core",
            "__ext_e5",
            0,
            1,
            extension_id="e5",
            nucleobase="C",
        ),
        nucleotide(
            "core",
            "__ext_e5",
            1,
            1.34,
            extension_id="e5",
            nucleobase="A",
        ),
        nucleotide("overhang", "ho", 0, 2, overhang_id="oh"),
        nucleotide("overhang", "ho", 1, 2.34, overhang_id="oh"),
    ]
    natural = _serialize_scene(
        design,
        nucleotides,
        [],
        coloring="base",
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    expanded = _serialize_scene(
        design,
        [
            {
                **nucleotide,
                "backbone_position": [
                    nucleotide["backbone_position"][0] + 5,
                    *nucleotide["backbone_position"][1:],
                ],
            }
            for nucleotide in nucleotides
        ],
        [],
        coloring="base",
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    scene = parse_scene_contract(_bundle_expanded_scene(natural, expanded))
    expected = {
        "nuc:core:0:h:0:FORWARD:0:backbone": pytest.approx(
            _BASE_COLORS_FOR_TEST["C"]
        ),
        "nuc:core:0:h:1:FORWARD:0:backbone": pytest.approx(
            _BASE_COLORS_FOR_TEST["G"]
        ),
        "nuc:core:0:__ext_e5:0:FORWARD:0:backbone": pytest.approx(
            _BASE_COLORS_FOR_TEST["C"]
        ),
        "nuc:core:0:__ext_e5:1:FORWARD:0:backbone": pytest.approx(
            _BASE_COLORS_FOR_TEST["A"]
        ),
        "nuc:overhang:0:ho:0:FORWARD:0:backbone": pytest.approx(
            _BASE_COLORS_FOR_TEST["G"]
        ),
        "nuc:overhang:0:ho:1:FORWARD:0:backbone": pytest.approx(
            _BASE_COLORS_FOR_TEST["C"]
        ),
    }
    for pose in ("full", "expanded/full"):
        points = {
            primitive.identity: primitive.values[7:10]
            for primitive in scene[pose].values()
            if primitive.record_type == "P"
        }
        assert points == expected


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
    atoms = [
        SimpleNamespace(
            name="C1'" if helix_id == "h1" else "O3'",
            x=x,
            y=0.0,
            z=0.0,
            strand_id="s1",
            helix_id=helix_id,
            bp_index=0,
            direction=direction,
            residue="DA",
            element="C",
        )
        for helix_id, direction, x in (
            ("h1", "FORWARD", 0.0),
            ("h2", "REVERSE", 2.0),
        )
    ]
    text = _serialize_scene(
        design,
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=atoms, bonds=[(0, 1)]),
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
    stick = parse_scene_contract(text)["stick"]
    atom_bond = next(
        primitive for primitive in stick.values() if primitive.record_type == "C"
    )
    assert _owner_token("crossover", "crossover", "xo-visible") in (
        atom_bond.owner_aliases
    )

    visible_periodic = _serialize_scene(
        design,
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=atoms, bonds=[(0, 1)]),
        show_periodic_seam_arcs=True,
    )
    visible_arcs = [
        primitive
        for primitive in parse_scene_contract(visible_periodic)["full"].values()
        if primitive.identity.endswith(":direct")
    ]
    assert {primitive.identity for primitive in visible_arcs} == {
        "crossover:xo-visible:direct",
        "ligation:h1:0:h3:0:direct",
        "ligation:h2:0:h3:0:direct",
    }
    periodic = next(
        primitive
        for primitive in visible_arcs
        if primitive.identity == "ligation:h2:0:h3:0:direct"
    )
    assert periodic.values[:6] == pytest.approx((2, 0, 0, 4, 0, 0))
    assert _owner_token(
        "crossover", "forced_ligation", "h2:0:h3:0"
    ) in periodic.owner_aliases


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
        cluster_transforms=[
            SimpleNamespace(
                id=f"c{index}",
                domain_ids=[],
                helix_ids=[f"h{index}"],
                auto_created=False,
                color=None,
                is_default=False,
            )
            for index in (1, 2)
        ],
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
    scene = parse_scene_contract(text)["full"]
    first_insert = scene["crossover:xo-extra:extra:0:bead"]
    assert set(first_insert.owner_aliases) == {
        _owner_token("base", "__xb__:xo-extra:0"),
        _owner_token("crossover", "crossover", "xo-extra"),
    }
    c1 = _owner_token("cluster", "c1")
    c2 = _owner_token("cluster", "c2")
    assert first_insert.transform_owners == (
        (c1, pytest.approx(2 / 3), pytest.approx(2 / 3)),
        (c2, pytest.approx(1 / 3), pytest.approx(1 / 3)),
    )
    first_edge = scene["crossover:xo-extra:extra-backbone:0"]
    assert first_edge.transform_owners == (
        (c1, 1.0, pytest.approx(2 / 3)),
        (c2, 0.0, pytest.approx(1 / 3)),
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
    parsed_marker = parse_scene_contract(text)["full"][
        "nuc:s1:1:__ext_e1:0:FORWARD:0:modification"
    ]
    assert _owner_token("extension", "e1") in parsed_marker.owner_aliases


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
    coarse = parse_scene_contract(text)["cylinders"][
        "segment:oh1:s1:0:0:0:coarse"
    ]
    assert _owner_token("overhang", "ov1") in coarse.owner_aliases

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
    design = _vr_linker_design("ss")
    design.cluster_transforms = [
        SimpleNamespace(
            id="left",
            domain_ids=[],
            helix_ids=["ha"],
            auto_created=False,
            color=None,
            is_default=False,
        ),
        SimpleNamespace(
            id="right",
            domain_ids=[],
            helix_ids=["hb"],
            auto_created=False,
            color=None,
            is_default=False,
        ),
    ]
    text = _serialize_scene(
        design,
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
    scene = parse_scene_contract(text)["full"]
    left = _owner_token("cluster", "left")
    right = _owner_token("cluster", "right")
    first_bead = scene["linker:link:ss:bead:0"]
    assert first_bead.transform_owners == (
        (left, pytest.approx(2 / 3), pytest.approx(2 / 3)),
        (right, pytest.approx(1 / 3), pytest.approx(1 / 3)),
    )
    first_edge = scene["linker:link:ss:backbone:0:near:0"]
    assert first_edge.transform_owners == (
        (left, 1.0, pytest.approx(47 / 48)),
        (right, 0.0, pytest.approx(1 / 48)),
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
    design = _vr_linker_design("ds")
    design.cluster_transforms = [
        SimpleNamespace(
            id="left",
            domain_ids=[],
            helix_ids=["ha"],
            auto_created=False,
            color=None,
            is_default=False,
        ),
        SimpleNamespace(
            id="right",
            domain_ids=[],
            helix_ids=["hb"],
            auto_created=False,
            color=None,
            is_default=False,
        ),
    ]
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
        design,
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
    scene = parse_scene_contract(text)["full"]
    left = _owner_token("cluster", "left")
    right = _owner_token("cluster", "right")
    assert scene["linker:link:ds:a:connector:0"].transform_owners == ((left, 1.0, 1.0),)
    assert scene["linker:link:ds:b:connector:0"].transform_owners == (
        (right, 1.0, 1.0),
    )


def test_ds_linker_cylinders_pair_overhang_halves_and_recover_bridge_axis() -> None:
    design = _vr_linker_design("ds")
    design.cluster_transforms = [
        SimpleNamespace(
            id="left",
            domain_ids=[],
            helix_ids=["ha"],
            auto_created=False,
            color=None,
            is_default=False,
        ),
        SimpleNamespace(
            id="right",
            domain_ids=[],
            helix_ids=["hb"],
            auto_created=False,
            color=None,
            is_default=False,
        ),
    ]
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
    bridge_owner = parse_scene_contract(text)["cylinders"]["linker:link:ds:bridge"]
    assert bridge_owner.transform_owners == (
        (_owner_token("cluster", "left"), 1.0, 0.0),
        (_owner_token("cluster", "right"), 0.0, 1.0),
    )


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
        cluster_transforms=[
            SimpleNamespace(
                id="left",
                domain_ids=[],
                helix_ids=["ha"],
                auto_created=False,
                color=None,
                is_default=False,
            ),
            SimpleNamespace(
                id="right",
                domain_ids=[],
                helix_ids=["hb"],
                auto_created=False,
                color=None,
                is_default=False,
            ),
        ],
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
        identity
        for identity in identities["full"]
        if identity.startswith("flex:flex-1:backbone:")
    ]
    assert len(flexible_backbones) == 32
    assert flexible_backbones[0].endswith(":near:0")
    assert flexible_backbones[-1].endswith(":near:1")
    scene = parse_scene_contract(text)["full"]
    left = _owner_token("cluster", "left")
    right = _owner_token("cluster", "right")
    first_bead = scene["flex:flex-1:bead:0"]
    assert first_bead.transform_owners == (
        (left, pytest.approx(2 / 3), pytest.approx(2 / 3)),
        (right, pytest.approx(1 / 3), pytest.approx(1 / 3)),
    )
    first_edge = scene["flex:flex-1:backbone:0:near:0"]
    assert first_edge.transform_owners == (
        (left, 1.0, pytest.approx(31 / 32)),
        (right, 0.0, pytest.approx(1 / 32)),
    )


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
        cluster_transforms=[
            SimpleNamespace(
                id="left",
                domain_ids=[],
                helix_ids=["h1"],
                auto_created=False,
                color=None,
                is_default=False,
            ),
            SimpleNamespace(
                id="right",
                domain_ids=[],
                helix_ids=["h2"],
                auto_created=False,
                color=None,
                is_default=False,
            ),
        ],
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
    warning = parse_scene_contract(text)["full"]["warning:xo-open:stem"]
    assert warning.transform_owners == (
        (_owner_token("cluster", "left"), 0.5, 0.5),
        (_owner_token("cluster", "right"), 0.5, 0.5),
    )
