"""Viewport annotations: persisted with the part, display-only, never a topology edit."""

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.assembly_polymer import _design_dump_for_identity
from backend.core.atomistic import atomistic_reference_topology_hash
from backend.core.models import Annotation, Design


def setup_function():
    design_state.set_design(_demo_design())


def _note(**over):
    body = {
        "id": "a1",
        "text": "Check this strand",
        "icon": "warning",
        "callout_type": "rounded",
        "color": "#ff4d4d",
        "transparency": 0.25,
        "size": 1.5,
        "manual": True,
        "screen_pos": [0.25, 0.5],
        "visible": True,
        "refs": [
            {"kind": "strand", "id": "s1"},
            {"kind": "domain", "strandId": "s1", "domainIndex": 2},
        ],
    }
    body.update(over)
    return body


def test_annotations_survive_a_file_round_trip_and_old_files_default_empty():
    design = _demo_design()
    design.annotations = [Annotation(**_note())]
    design.annotations_enabled = False
    restored = Design.from_json(design.to_json())
    assert restored.annotations == design.annotations
    assert restored.annotations[0].refs[1]["domainIndex"] == 2
    assert restored.annotations_enabled is False
    fresh = Design.from_json(_demo_design().to_json())
    assert fresh.annotations == [] and fresh.annotations_enabled is True


def test_put_annotations_persists_without_an_undo_entry():
    client = TestClient(app)
    depth, revision = design_state.undo_depth(), design_state.revision()
    response = client.put(
        "/api/design/annotations", json={"annotations": [_note()], "enabled": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["annotations"][0]["text"] == "Check this strand"
    assert body["annotations_enabled"] is False
    assert body["revision"] > revision
    assert design_state.undo_depth() == depth
    saved = design_state.get_or_404()
    assert [a.id for a in saved.annotations] == [
        "a1"
    ] and saved.annotations_enabled is False
    # And it is what the file writer would emit.
    assert Design.from_json(saved.to_json()).annotations[0].screen_pos == (0.25, 0.5)


def test_put_annotations_validates():
    client = TestClient(app)
    put = lambda **over: (
        client.put(
            "/api/design/annotations", json={"annotations": [_note(**over)]}
        ).status_code
    )
    assert put() == 200
    assert put(color="red") == 422
    assert put(callout_type="wavy") == 422
    assert put(transparency=1.5) == 422
    assert put(size=0) == 422
    assert put(screen_pos=[2, 0]) == 422
    assert put(refs=[{"id": "x"}]) == 422
    assert (
        client.put(
            "/api/design/annotations", json={"annotations": [_note(), _note()]}
        ).status_code
        == 422
    )


def test_undo_and_redo_never_rewind_or_resurrect_annotations():
    client = TestClient(app)
    # A real (undoable) edit first, then annotate, then undo that edit.
    design_state.set_design(
        design_state.get_or_404().model_copy(
            update={"lattice_type": design_state.get_or_404().lattice_type}, deep=True
        )
    )
    assert (
        client.put(
            "/api/design/annotations", json={"annotations": [_note()], "enabled": True}
        ).status_code
        == 200
    )
    assert client.post("/api/design/undo").status_code == 200
    assert [a.id for a in design_state.get_or_404().annotations] == ["a1"]
    assert client.post("/api/design/redo").status_code == 200
    assert [a.id for a in design_state.get_or_404().annotations] == ["a1"]
    # Deleting them is likewise not undone.
    assert (
        client.put("/api/design/annotations", json={"annotations": []}).status_code
        == 200
    )
    design_state.set_design(design_state.get_or_404().model_copy(deep=True))
    assert client.post("/api/design/undo").status_code == 200
    assert design_state.get_or_404().annotations == []


def test_annotations_do_not_change_topology_identity_or_atomistic_hash():
    design = _demo_design()
    before = (
        _design_dump_for_identity(design),
        atomistic_reference_topology_hash(design),
    )
    design.annotations = [Annotation(**_note())]
    design.annotations_enabled = False
    assert (
        _design_dump_for_identity(design),
        atomistic_reference_topology_hash(design),
    ) == before
