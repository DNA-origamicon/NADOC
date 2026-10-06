"""Circular pattern placement, unchanged sources, and transactional history."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from fastapi.testclient import TestClient

from backend.core.circular_pattern import create_circular_pattern, pattern_angles
from backend.core.lattice import make_bundle_segment
from backend.core.models import Design, ClusterRigidTransform
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.lattice_frames import append_independent_bundle


def source_design():
    d = make_bundle_segment(Design(), [(0, 1), (1, 1), (1, 2)], 21, "XY", 0, "both")
    return d.copy_with(
        cluster_transforms=[
            ClusterRigidTransform(
                id="source",
                name="Source",
                helix_ids=[h.id for h in d.helices],
                translation=[8, 3, 4],
                rotation=Rotation.from_euler("y", 30, degrees=True).as_quat().tolist(),
            )
        ]
    )


def test_angle_endpoints_and_validation():
    assert np.allclose(pattern_angles(4, 360), np.arange(4) * np.pi / 2)
    assert np.allclose(pattern_angles(3, 180), [0, np.pi / 2, np.pi])
    assert pattern_angles(1, 360) == [0]
    for count, degrees in [(0, 360), (129, 360), (2.5, 360), (2, 0), (2, float("nan"))]:
        with pytest.raises(ValueError):
            pattern_angles(count, degrees)


@pytest.mark.parametrize("framed", [False, True])
def test_copies_match_world_space_preview_and_keep_canonical_cells(framed):
    d = source_design()
    if framed:
        d = append_independent_bundle(
            Design(),
            [[0, 0], [0, 1]],
            21,
            translation_nm=[8, 3, 4],
            rotation_xyzw=Rotation.from_euler("y", 30, degrees=True).as_quat().tolist(),
        )
    before = d.model_dump_json()
    point = np.array([13.0, 9.0, 1.0])
    direction = np.array([1.0, 2.0, 3.0])
    direction /= np.linalg.norm(direction)
    out, ids, _ = create_circular_pattern(
        d, d.cluster_transforms[0].id, 3, 180, point, direction
    )
    assert len(ids) == len(d.helices) * 2
    assert d.model_dump_json() == before
    assert out.helices[: len(d.helices)] == d.helices
    # Revalidate persisted frame references as loading a saved file would.
    Design.model_validate_json(out.model_dump_json())
    for copy_index, angle in enumerate(pattern_angles(3, 180)[1:]):
        r = Rotation.from_rotvec(direction * angle).as_matrix()
        for i, original in enumerate(d.helices):
            copied = out.helices[len(d.helices) * (copy_index + 1) + i]
            assert copied.grid_pos == original.grid_pos
            assert copied.lattice_frame_id != original.lattice_frame_id
            source = deformed_nucleotide_arrays(original, d)
            target = deformed_nucleotide_arrays(copied, out)
            for field in ("positions", "base_positions"):
                expected = (source[field] - point) @ r.T + point
                assert np.allclose(target[field], expected, atol=1e-8)


def test_api_confirm_is_one_undo_step_and_rejects_invalid_requests():
    from backend.api import state
    from backend.api.main import app
    from backend.api.headless_build import scratch_session
    from backend.core.models import LatticeType

    with scratch_session(LatticeType.HONEYCOMB):
        d = source_design()
        state.set_design(d)
        from backend.api.doc_context import get_current_doc

        client = TestClient(app, headers={"X-NADOC-Doc": get_current_doc()})
        body = {
            "cluster_id": "source",
            "instances": 3,
            "total_angle": 360,
            "axis_point": [20, 0, 0],
            "axis_direction": [0, 0, 1],
        }
        response = client.post("/api/design/circular-pattern", json=body)
        assert response.status_code == 200, response.text
        result = state.get_or_404()
        assert len(result.helices) == len(d.helices) * 3
        assert result.feature_log[-1].op_kind == "circular-pattern"
        assert client.post("/api/design/undo").status_code == 200
        assert state.get_or_404().helices == d.helices
        assert client.post("/api/design/redo").status_code == 200
        assert state.get_or_404().helices == result.helices
        assert (
            client.post("/api/design/features/seek", json={"position": -2}).status_code
            == 200
        )
        assert state.get_or_404().helices == d.helices
        assert state.get_or_404().lattice_frames == []
        assert len(state.get_or_404().cluster_transforms) == 1
        assert (
            client.post("/api/design/features/seek", json={"position": -1}).status_code
            == 200
        )
        assert state.get_or_404().helices == result.helices
        assert state.get_or_404().lattice_frames == result.lattice_frames
        Design.model_validate_json(state.get_or_404().model_dump_json())
        before = state.get_or_404().model_dump_json()
        assert (
            client.post(
                "/api/design/circular-pattern",
                json={**body, "axis_direction": [0, 0, 0]},
            ).status_code
            == 400
        )
        assert state.get_or_404().model_dump_json() == before
        assert client.delete("/api/design/features/0").status_code == 200
        remaining = state.get_or_404()
        assert remaining.helices == d.helices
        assert remaining.lattice_frames == []
        Design.model_validate_json(remaining.model_dump_json())


def test_pattern_preserves_twist_and_distinct_overlapping_poses():
    from backend.core.models import DeformationOp, TwistParams

    d = source_design()
    child = ClusterRigidTransform(
        id="child", helix_ids=[d.helices[0].id], translation=[1, 2, 3]
    )
    d = d.copy_with(
        cluster_transforms=[*d.cluster_transforms, child],
        deformations=[
            DeformationOp(
                type="twist",
                plane_a_bp=0,
                plane_b_bp=20,
                affected_helix_ids=[h.id for h in d.helices],
                params=TwistParams(total_degrees=25),
            )
        ],
    )
    out, _, _ = create_circular_pattern(d, "source", 2, 180, [9, 8, 7], [1, 0, 0])
    r = Rotation.from_euler("x", 180, degrees=True).as_matrix()
    p = np.array([9, 8, 7])
    for original, copied in zip(d.helices, out.helices[len(d.helices) :], strict=True):
        expected = (deformed_nucleotide_arrays(original, d)["positions"] - p) @ r.T + p
        assert np.allclose(
            deformed_nucleotide_arrays(copied, out)["positions"], expected, atol=1e-8
        )
        assert np.allclose(
            deformed_nucleotide_arrays(out.helices[d.helices.index(original)], out)[
                "positions"
            ],
            deformed_nucleotide_arrays(original, d)["positions"],
        )


def test_twisted_pattern_survives_history_seek():
    from backend.api import state
    from backend.api.crud import _seek_feature_log
    from backend.core.models import (
        DeformationOp,
        TwistParams,
        DeformationLogEntry,
        SnapshotLogEntry,
    )

    d = source_design()
    op = DeformationOp(
        type="twist",
        plane_a_bp=0,
        plane_b_bp=20,
        affected_helix_ids=[h.id for h in d.helices],
        params=TwistParams(total_degrees=25),
    )
    d = d.copy_with(
        deformations=[op],
        feature_log=[DeformationLogEntry(deformation_id=op.id, op_snapshot=op)],
    )
    out, _, _ = create_circular_pattern(d, "source", 2, 180, [9, 8, 7], [1, 0, 0])
    pre, _ = state.encode_design_snapshot(d)
    post, _ = state.encode_design_snapshot(out)
    entry = SnapshotLogEntry(
        op_kind="circular-pattern",
        label="Pattern",
        design_snapshot_gz_b64=pre,
        post_state_gz_b64=post,
    )
    out = out.copy_with(feature_log=[*d.feature_log, entry])
    back = _seek_feature_log(out, 0)
    assert back.helices == d.helices
    restored = _seek_feature_log(back, -1)
    assert restored.deformations == out.deformations
    assert restored.lattice_frames == out.lattice_frames
    Design.model_validate_json(restored.model_dump_json())
    for h in out.helices:
        assert np.allclose(
            deformed_nucleotide_arrays(h, out)["positions"],
            deformed_nucleotide_arrays(h, restored)["positions"],
        )
