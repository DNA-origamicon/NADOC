"""Native Join transport preserves the launch frame and draft ordering."""
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.api.vr_join import JoinFeedback, record, publish


def feedback(**changes):
    return JoinFeedback(**{
        "sequence": 4, "tool_sequence": 7, "request_sequence": 11,
        "status": "valid", "valid": True, "connection_count": 2,
        "message": "2 connections · Apply",
        "bridges": [{"a": [1, 2, 3], "b": [4, 5, 6]}],
        "sites": [{"moving": True, "position": [1, 0, 2], "normal": [0, 0, 1]}],
        **changes,
    })


def test_join_feedback_rotates_both_bridge_ends_and_attachment_normals():
    lines = record(feedback(), [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]).splitlines()
    assert lines[0] == "NADOC_JOIN_1 4 7 11 valid 1 2 1 1 2%20connections%20%2F%20Apply"
    assert list(map(float, lines[1].split())) == [3, 2, -1, 6, 5, -4]
    assert list(map(float, lines[2].split())) == [1, 2, 0, -1, 1, 0, 0]


@pytest.mark.parametrize("changes", [
    {"sequence": 0}, {"sequence": 2**53}, {"request_sequence": -1},
    {"status": "unknown"}, {"message": "a" * 513},
    {"bridges": [{"a": [float("nan"), 0, 0], "b": [0, 0, 0]}]},
    {"sites": [{"moving": False, "position": [0, 0, 0], "normal": [0, float("inf"), 1]}]},
    {"bridges": [{"a": [0, 0, 0], "b": [1, 0, 0]}] * 129},
    {"sites": [{"moving": True, "position": [0, 0, 0], "normal": [1, 0, 0]}] * 8193},
])
def test_join_feedback_rejects_malformed_or_unbounded_packets(changes):
    with pytest.raises(ValidationError):
        feedback(**changes)


def test_join_feedback_rejects_bad_launch_frame_and_extreme_geometry():
    for rotation in (np.eye(2), [[1, 0, 0], [0, float("nan"), 0], [0, 0, 1]]):
        with pytest.raises(HTTPException, match="Invalid VR view rotation"):
            record(feedback(), rotation)
    with pytest.raises(HTTPException, match="Invalid VR Join geometry"):
        record(feedback(bridges=[{"a": [1e10, 0, 0], "b": [0, 0, 0]}]), np.eye(3))


def test_join_feedback_publication_is_private_atomic_ordered_and_document_bound(tmp_path, monkeypatch):
    from backend.api import routes_vr as vr
    from backend.api import doc_context

    state = {"doc_id": "join-doc", "event_path": str(tmp_path / "events.json"), "view_rotation": np.eye(3).tolist()}
    monkeypatch.setattr(vr, "_read_state", lambda: state)
    monkeypatch.setattr(doc_context, "get_current_doc", lambda: "join-doc")
    request = Request({"type": "http", "client": ("127.0.0.1", 9999), "headers": []})
    path = Path(state["event_path"] + ".join")
    assert publish(feedback(), request) == {"published": True, "current_sequence": 4}
    checked = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_name(path.name + ".next").exists()
    assert publish(feedback(sequence=3, valid=False, status="checking"), request)["published"] is False
    assert path.read_bytes() == checked
    assert publish(feedback(sequence=5, valid=False, status="cancelled", bridges=[], sites=[]), request)["published"] is True
    assert " cancelled 0 " in path.read_text()
    monkeypatch.setattr(doc_context, "get_current_doc", lambda: "another-doc")
    with pytest.raises(HTTPException) as exc:
        publish(feedback(sequence=6), request)
    assert exc.value.status_code == 409
    assert " cancelled 0 " in path.read_text()


def test_join_tool_and_transform_survive_native_event_envelope(tmp_path):
    from backend.api.routes_vr import _event_payload

    path = tmp_path / "event.json"
    path.write_text(json.dumps({
        "sequence": 2, "tool_sequence": 3, "tool_mode": "join", "tool_action": "preview",
        "transform_sequence": 4,
        "transform_matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 6, 7, 1],
    }))
    payload = _event_payload({"event_path": str(path), "view_rotation": np.eye(3).tolist()})
    assert payload["tool_mode"] == "join"
    assert payload["tool_action"] == "preview"
    assert payload["transform_sequence"] == 4
    assert payload["transform_matrix"][12:15] == [5, 6, 7]
