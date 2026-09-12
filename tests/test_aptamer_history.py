"""Exercise G4 history through the same HTTP routes used by the editor."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.spatial.transform import Rotation

from backend.api import state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.deformation import deformed_helix_axes
from backend.core.models import Design


@pytest.fixture
def client():
    state.load_design(None)
    state.clear_history()
    yield TestClient(app)
    state.load_design(None)
    state.clear_history()


def request(client, method, path, **kwargs):
    response = client.request(method, "/api/design/" + path, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def import_g4(client, pid="148D"):
    request(client, "POST", "import/aptamer", json={"template_id": pid})
    return state.get_design().model_copy(deep=True)


def assert_pose(
    design, baseline, translation=(0, 0, 0), rotation=(0, 0, 0, 1), pivot=(0, 0, 0)
):
    r = Rotation.from_quat(rotation)
    expected = np.array(
        [n["backbone_position"] for n in _geometry_for_design(baseline)]
    )
    expected = r.apply(expected - pivot) + pivot + np.array(translation)
    actual = _geometry_for_design(design)
    np.testing.assert_allclose(
        [n["backbone_position"] for n in actual], expected, atol=1e-9
    )
    atoms = {
        (a.strand_id, a.bp_index): a
        for a in build_atomistic_model(design).atoms
        if a.name == "C1'"
    }
    for n, p in zip(actual, expected):
        a = atoms[n["strand_id"], n["bp_index"]]
        np.testing.assert_allclose([a.x, a.y, a.z], p, atol=1e-9)
    np.testing.assert_allclose(
        deformed_helix_axes(design)[0]["samples"], expected, atol=1e-9
    )
    assert [s.id for s in design.strands] == [s.id for s in baseline.strands]
    assert [h.native_residues for h in design.helices] == [
        h.native_residues for h in baseline.helices
    ]


def test_first_import_is_logged_undoable_and_seekable(client):
    baseline = import_g4(client)
    assert len(baseline.feature_log) == 1
    assert baseline.feature_log[0].op_kind == "aptamer-import"
    request(client, "POST", "undo")
    assert not state.get_design().strands
    assert not state.get_design().feature_log
    request(client, "POST", "redo")
    assert_pose(state.get_design(), baseline)
    request(client, "POST", "features/seek", json={"position": -2})
    assert not state.get_design().strands
    request(client, "POST", "features/seek", json={"position": -1})
    assert_pose(state.get_design(), baseline)
    # Persisted snapshots must restore sites even without session undo stacks.
    saved = Design.model_validate_json(state.get_design().model_dump_json())
    state.load_design(saved)
    request(client, "POST", "features/seek", json={"position": -2})
    request(client, "POST", "features/seek", json={"position": 0})
    assert_pose(state.get_design(), baseline)


def test_move_rotate_edit_delete_and_revert_preserve_native_sites(client):
    baseline = import_g4(client)
    cid = baseline.cluster_transforms[0].id
    move = dict(translation=[4, -3, 2], rotation=[0, 0, 0, 1], pivot=[1, 2, -1])
    rotate = {
        **move,
        "rotation": Rotation.from_euler("xyz", [30, 45, 70], degrees=True)
        .as_quat()
        .tolist(),
    }
    for pose in (move, rotate):
        request(client, "PATCH", f"cluster/{cid}", json={**pose, "commit": True})
        assert_pose(state.get_design(), baseline, **pose)
    assert [e.feature_type for e in state.get_design().feature_log] == [
        "snapshot",
        "cluster_op",
        "cluster_op",
    ]
    request(client, "POST", "undo")
    assert_pose(state.get_design(), baseline, **move)
    request(client, "POST", "redo")
    assert_pose(state.get_design(), baseline, **rotate)
    request(client, "POST", "features/seek", json={"position": 0})
    assert_pose(state.get_design(), baseline)
    request(client, "POST", "features/seek", json={"position": 1})
    assert_pose(state.get_design(), baseline, **move)
    request(client, "POST", "features/seek", json={"position": -1})
    assert_pose(state.get_design(), baseline, **rotate)
    edited = {**rotate, "translation": [-1, 5, 8]}
    request(client, "POST", "features/2/edit", json={"params": edited})
    assert_pose(state.get_design(), baseline, **edited)
    request(client, "POST", "undo")
    assert_pose(state.get_design(), baseline, **rotate)
    request(client, "POST", "redo")
    assert_pose(state.get_design(), baseline, **edited)
    request(client, "DELETE", "features/2")
    assert_pose(state.get_design(), baseline, **move)
    request(client, "POST", "undo")
    assert_pose(state.get_design(), baseline, **edited)
    request(client, "POST", "features/1/revert")
    assert_pose(state.get_design(), baseline)
    assert len(state.get_design().feature_log) == 1
    request(client, "POST", "undo")
    assert_pose(state.get_design(), baseline, **edited)


def test_import_delete_handles_dependent_moves_and_independent_imports(client):
    first = import_g4(client)
    second = import_g4(client, "2HY9")
    cid = first.cluster_transforms[0].id
    request(
        client,
        "PATCH",
        f"cluster/{cid}",
        json={"translation": [1, 2, 3], "commit": True},
    )
    before = state.get_design().model_dump_json()
    result = request(client, "DELETE", "features/0")
    assert result["needs_cascade_decision"]
    assert state.get_design().model_dump_json() == before
    request(client, "DELETE", "features/0?cascade=true")
    remaining = state.get_design()
    assert len(remaining.strands) == 1
    assert remaining.strands[0].id == second.strands[1].id
    assert len(remaining.feature_log) == 1
    request(client, "POST", "undo")
    assert len(state.get_design().strands) == 2
    request(client, "POST", "redo")
    assert len(state.get_design().strands) == 1


def test_resize_log_substeps_restore_fold_and_sequence(client):
    baseline = import_g4(client)
    sid = baseline.strands[0].id
    hid = baseline.helices[0].id
    for end, delta in [("5p", -2), ("3p", 3)]:
        request(
            client,
            "POST",
            "strand-end-resize",
            json={
                "entries": [
                    {"strand_id": sid, "helix_id": hid, "end": end, "delta_bp": delta}
                ]
            },
        )
    assert (
        state.get_design().strands[0].sequence
        == "NN" + baseline.strands[0].sequence + "NNN"
    )
    request(client, "POST", "undo")
    assert state.get_design().strands[0].sequence == "NN" + baseline.strands[0].sequence
    request(client, "POST", "undo")
    assert_pose(state.get_design(), baseline)
    request(client, "POST", "redo")
    request(client, "POST", "redo")
    request(client, "POST", "features/seek", json={"position": 0})
    assert_pose(state.get_design(), baseline)
    request(client, "POST", "features/seek", json={"position": -1})
    assert (
        state.get_design().strands[0].sequence
        == "NN" + baseline.strands[0].sequence + "NNN"
    )
