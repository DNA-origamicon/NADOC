"""Linear geometry, multi-cluster copies, and both editable pattern histories."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.linear_pattern import (
    create_linear_pattern,
    linear_direction,
    linear_offsets,
)
from backend.core.models import Design, ClusterRigidTransform, LatticeType
from tests.test_circular_pattern import source_design


def test_offsets_and_invalid_patterns():
    offsets = linear_offsets(
        3, -12, "Z", two_dimensional=True, instances2=2, spacing2=8, direction2="X"
    )
    assert np.allclose(
        [p for _, p in offsets],
        [[0, 0, 0], [0, 0, -12], [0, 0, -24], [8, 0, 0], [8, 0, -12], [8, 0, -24]],
    )
    for params in [
        dict(instances=0),
        dict(instances=2.5),
        dict(spacing=0),
        dict(spacing=float("nan")),
        dict(direction="W"),
        dict(two_dimensional=True, direction2="X"),
        dict(two_dimensional=True, instances=65),
    ]:
        with pytest.raises(ValueError):
            linear_offsets(**{**dict(instances=3, spacing=10, direction="X"), **params})


def test_grid_copies_transformed_cluster_without_rotating_or_mutating_source():
    d = source_design()
    before = d.model_dump_json()
    out, ids, _ = create_linear_pattern(
        d,
        ["source"],
        3,
        12,
        "X",
        two_dimensional=True,
        instances2=2,
        spacing2=-8,
        direction2="Y",
    )
    assert d.model_dump_json() == before
    assert len(ids) == 15
    Design.model_validate_json(out.model_dump_json())
    for n, (_, offset) in enumerate(
        linear_offsets(
            3, 12, "X", two_dimensional=True, instances2=2, spacing2=-8, direction2="Y"
        )
    ):
        for i, source in enumerate(d.helices):
            copied = out.helices[n * 3 + i]
            assert copied.grid_pos == source.grid_pos
            assert np.allclose(
                deformed_nucleotide_arrays(copied, out)["positions"],
                deformed_nucleotide_arrays(source, d)["positions"] + offset,
            )


def test_multiple_clusters_and_overlap_rejection():
    d = source_design()
    d = d.copy_with(
        cluster_transforms=[
            d.cluster_transforms[0].model_copy(update={"helix_ids": [d.helices[0].id]}),
            ClusterRigidTransform(
                id="second",
                helix_ids=[h.id for h in d.helices[1:]],
                translation=[0, 9, 0],
            ),
        ]
    )
    out, ids, reports = create_linear_pattern(d, ["source", "second"], 2, 10, "Z")
    assert len(ids) == 3 and reports[0].requested_cluster_ids == ["source", "second"]
    for source, copied in zip(d.helices, out.helices[3:], strict=True):
        assert np.allclose(
            deformed_nucleotide_arrays(copied, out)["positions"],
            deformed_nucleotide_arrays(source, d)["positions"] + [0, 0, 10],
        )
    d.cluster_transforms[1].helix_ids.append(d.helices[0].id)
    with pytest.raises(ValueError, match="overlap"):
        create_linear_pattern(d, ["source", "second"], 2, 10, "Z")


def test_selected_union_preserves_strands_between_clusters():
    d = source_design()
    first, last = d.strands[0], d.strands[-1]
    joined = first.model_copy(update={"domains": [*first.domains, *last.domains]})
    d = d.copy_with(
        strands=[joined, *d.strands[1:-1]],
        cluster_transforms=[
            d.cluster_transforms[0].model_copy(update={"helix_ids": [d.helices[0].id]}),
            ClusterRigidTransform(id="second", helix_ids=[h.id for h in d.helices[1:]]),
        ],
    )
    out, ids, reports = create_linear_pattern(d, ["source", "second"], 2, 15, "Y")
    assert reports[0].truncated_strand_count == 0
    assert len(out.strands) == len(d.strands) * 2
    copied = out.strands[len(d.strands)]
    assert len(copied.domains) == len(joined.domains)
    assert all(domain.helix_id in ids for domain in copied.domains)


@pytest.fixture
def session():
    from backend.api import state
    from backend.api.main import app
    from backend.api.doc_context import get_current_doc
    from backend.api.headless_build import scratch_session

    with scratch_session(LatticeType.HONEYCOMB):
        state.set_design(source_design())
        yield TestClient(app, headers={"X-NADOC-Doc": get_current_doc()}), state


LINEAR = dict(
    cluster_ids=["source"],
    instances=3,
    spacing=10,
    direction="X",
    two_dimensional=True,
    instances2=2,
    spacing2=15,
    direction2="Z",
)
CIRCULAR = dict(
    cluster_id="source",
    instances=3,
    total_angle=180,
    axis_point=[20, 0, 0],
    axis_direction=[0, 0, 1],
)


@pytest.mark.parametrize(
    "kind,params,edit",
    [
        ("linear-pattern", LINEAR, dict(instances=2, spacing=-20)),
        ("circular-pattern", CIRCULAR, dict(instances=2, total_angle=90)),
    ],
)
def test_create_edit_undo_redo_seek_and_reload(session, kind, params, edit):
    client, state = session
    original = state.get_or_404()
    response = client.post(f"/api/design/{kind}", json=params)
    assert response.status_code == 200, response.text
    created = state.get_or_404()
    assert len(created.feature_log) == 1
    response = client.post("/api/design/features/0/edit", json={"params": edit})
    assert response.status_code == 200, response.text
    edited = state.get_or_404()
    expected_count = 4 if kind == "linear-pattern" else 2
    assert len(edited.helices) == 3 * expected_count
    assert len(edited.feature_log) == 1
    assert edited.feature_log[0].id == created.feature_log[0].id
    assert edited.feature_log[0].params["instances"] == 2
    source_positions = deformed_nucleotide_arrays(original.helices[0], original)[
        "positions"
    ]
    copy_positions = deformed_nucleotide_arrays(edited.helices[3], edited)["positions"]
    if kind == "linear-pattern":
        assert np.allclose(copy_positions, source_positions + [-20, 0, 0])
    else:
        from scipy.spatial.transform import Rotation

        rotation = Rotation.from_euler("z", 90, degrees=True).as_matrix()
        assert np.allclose(
            copy_positions, (source_positions - [20, 0, 0]) @ rotation.T + [20, 0, 0]
        )
    # The first copy survives with all IDs intact, including strand fragments.
    assert edited.helices[3:6] == created.helices[3:6]
    assert (
        edited.strands[: len(original.strands) * 2]
        == created.strands[: len(original.strands) * 2]
    )
    assert client.post("/api/design/undo").status_code == 200
    assert state.get_or_404().model_dump() == created.model_dump()
    assert client.post("/api/design/redo").status_code == 200
    assert state.get_or_404().model_dump() == edited.model_dump()
    state.set_design(Design.model_validate_json(edited.model_dump_json()))
    assert (
        client.post("/api/design/features/seek", json={"position": -2}).status_code
        == 200
    )
    assert state.get_or_404().helices == original.helices
    assert (
        client.post("/api/design/features/seek", json={"position": -1}).status_code
        == 200
    )
    restored = state.get_or_404()
    assert restored.lattice_frames == edited.lattice_frames
    for h in edited.helices:
        assert np.allclose(
            deformed_nucleotide_arrays(h, restored)["positions"],
            deformed_nucleotide_arrays(h, edited)["positions"],
        )
    assert client.delete("/api/design/features/0").status_code == 200
    assert state.get_or_404().helices == original.helices


def test_edit_preserves_independent_later_pattern_and_rejects_dependents(session):
    client, state = session
    assert client.post("/api/design/circular-pattern", json=CIRCULAR).status_code == 200
    assert client.post("/api/design/linear-pattern", json=LINEAR).status_code == 200
    before = state.get_or_404()
    later_ids = [h.id for h in before.helices[9:]]
    response = client.post(
        "/api/design/features/0/edit", json={"params": {"instances": 2}}
    )
    assert response.status_code == 200, response.text
    after = state.get_or_404()
    assert len(after.feature_log) == 2
    assert [h.id for h in after.helices[6:]] == later_ids
    assert (
        client.post(
            "/api/design/features/1/edit", json={"params": {"instances": 2}}
        ).status_code
        == 200
    )
    copied_cluster = state.get_or_404().cluster_transforms[1].id
    assert (
        client.post(
            "/api/design/linear-pattern",
            json={**LINEAR, "cluster_ids": [copied_cluster]},
        ).status_code
        == 200
    )
    before = state.get_or_404().model_dump_json()
    response = client.post(
        "/api/design/features/0/edit", json={"params": {"instances": 4}}
    )
    assert response.status_code == 409, response.text
    assert state.get_or_404().model_dump_json() == before


def test_invalid_requests_leave_history_and_redo_unchanged(session):
    client, state = session
    assert client.post("/api/design/linear-pattern", json=LINEAR).status_code == 200
    assert client.post("/api/design/undo").status_code == 200
    before = state.get_or_404().model_dump_json()
    for patch in [
        dict(spacing=0),
        dict(direction2="X"),
        dict(instances=100),
        dict(cluster_ids=["missing"]),
        dict(instances=2.5),
    ]:
        response = client.post("/api/design/linear-pattern", json={**LINEAR, **patch})
        assert response.status_code in {400, 422}, response.text
        assert state.get_or_404().model_dump_json() == before
    assert client.post("/api/design/redo").status_code == 200
    before = state.get_or_404().model_dump_json()
    assert (
        client.post(
            "/api/design/features/0/edit", json={"params": {"spacing": 0}}
        ).status_code
        == 400
    )
    assert state.get_or_404().model_dump_json() == before


def test_edit_and_seek_preserve_later_moves_and_pattern_baseline(session):
    client, state = session
    params = {**LINEAR, "instances": 2, "two_dimensional": False}
    assert client.post("/api/design/linear-pattern", json=params).status_code == 200
    copied = state.get_or_404().cluster_transforms[1]
    assert (
        client.patch(
            f"/api/design/cluster/{copied.id}",
            json={"translation": [80, 90, 100], "commit": True},
        ).status_code
        == 200
    )
    response = client.post(
        "/api/design/features/0/edit", json={"params": {"spacing": 25}}
    )
    assert response.status_code == 200, response.text
    assert state.get_or_404().cluster_transforms[1].translation == [80, 90, 100]
    assert (
        client.post("/api/design/features/seek", json={"position": 0}).status_code
        == 200
    )
    at_pattern = state.get_or_404()
    assert np.allclose(
        at_pattern.cluster_transforms[1].translation,
        np.array(copied.translation) + [15, 0, 0],
    )
    # Editing while scrubbed still restores and preserves the complete later history.
    assert (
        client.post(
            "/api/design/features/0/edit", json={"params": {"instances": 3}}
        ).status_code
        == 200
    )
    assert state.get_or_404().cluster_transforms[1].translation == [80, 90, 100]
    before = state.get_or_404().model_dump_json()
    assert (
        client.post(
            "/api/design/features/0/edit", json={"params": {"instances": 1}}
        ).status_code
        == 409
    )
    assert state.get_or_404().model_dump_json() == before


def test_custom_directions_are_normalized_and_nonparallel():
    assert np.allclose(linear_direction("Custom", [0, 3, 4]), [0, 0.6, 0.8])
    for vector in ([0, 0, 0], [float("nan"), 1, 0], [1, 2]):
        with pytest.raises(ValueError):
            linear_direction("Custom", vector)
    params = dict(
        instances=3,
        spacing=10,
        direction="Custom",
        vector=[3, 4, 0],
        two_dimensional=True,
        instances2=2,
        spacing2=5,
        direction2="Custom",
        vector2=[-4, 3, 0],
    )
    assert np.allclose(
        [p for _, p in linear_offsets(**params)],
        [[0, 0, 0], [6, 8, 0], [12, 16, 0], [-4, 3, 0], [2, 11, 0], [8, 19, 0]],
    )
    with pytest.raises(ValueError, match="nonparallel"):
        linear_offsets(**{**params, "vector2": [-6, -8, 0]})


def test_custom_vector_creation_edit_history_and_invalid_edit(session):
    client, state = session
    source = state.get_or_404()
    params = {
        **LINEAR,
        "direction": "Custom",
        "vector": [0, 3, 4],
        "direction2": "Custom",
        "vector2": [2, 0, 0],
        "spacing": 10,
        "spacing2": -5,
    }
    response = client.post("/api/design/linear-pattern", json=params)
    assert response.status_code == 200, response.text
    created = state.get_or_404()
    base = deformed_nucleotide_arrays(source.helices[0], source)["positions"]
    assert np.allclose(
        deformed_nucleotide_arrays(created.helices[3], created)["positions"],
        base + [0, 6, 8],
    )
    assert np.allclose(
        deformed_nucleotide_arrays(created.helices[9], created)["positions"],
        base + [-5, 0, 0],
    )
    assert "Custom (0, 3, 4)" in created.feature_log[-1].label
    response = client.post(
        "/api/design/features/0/edit",
        json={"params": {"vector": [0, -4, 3], "spacing": 5}},
    )
    assert response.status_code == 200, response.text
    edited = state.get_or_404()
    assert edited.helices[3].id == created.helices[3].id
    assert np.allclose(
        deformed_nucleotide_arrays(edited.helices[3], edited)["positions"],
        base + [0, -4, 3],
    )
    assert client.post("/api/design/undo").status_code == 200
    assert state.get_or_404().feature_log[0].params["vector"] == [0, 3, 4]
    assert client.post("/api/design/redo").status_code == 200
    restored = Design.model_validate_json(state.get_or_404().model_dump_json())
    assert restored.feature_log[0].params["vector"] == [0, -4, 3]
    before = state.get_or_404().model_dump_json()
    for vector in ([0, 0, 0], [1, 0, 0], [1, 2]):
        assert (
            client.post(
                "/api/design/features/0/edit", json={"params": {"vector": vector}}
            ).status_code
            == 400
        )
        assert state.get_or_404().model_dump_json() == before
