"""Indexed-sweep display axes retain legacy frame/segment geometry without repeated fits."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core import deformation, sweep_path
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.lattice import make_bundle_design
from backend.core.models import BendParams, ClusterRigidTransform, DeformationOp, LatticeType
from backend.core.sweep_model import SweepParams


def _design(start_bp=0, extra_op=None):
    count = 43
    seed = make_bundle_design([(0, 0), (1, 0)], count, offset_nm=start_bp * RISE,
                              lattice_type=LatticeType.SQUARE)
    theta = np.linspace(0, np.pi, count)
    radius = (count - 1) * RISE / np.pi
    points = np.column_stack([radius * (1 - np.cos(theta)), np.zeros(count), radius * np.sin(theta)])
    points += [10, -3, 8]
    frames = Rotation.from_euler("y", theta[:, None]).as_matrix()
    sweep = DeformationOp(id="sweep", type="sweep", plane_a_bp=start_bp,
        plane_b_bp=start_bp + count - 1, affected_helix_ids=[h.id for h in seed.helices],
        params=SweepParams(points_nm=[points[0].tolist(), points[-1].tolist()],
            origin_nm=(0, 0, 0), initial_rotation=np.eye(3).ravel().tolist(),
            steps=count - 1, path_length_nm=(count - 1) * RISE,
            bp_positions_nm=points.tolist(), bp_frames=frames.reshape(-1, 9).tolist()))
    operations = [sweep]
    if extra_op is not None:
        bend = DeformationOp(id="bend", type="bend", plane_a_bp=start_bp,
            plane_b_bp=start_bp + count - 1, affected_helix_ids=[seed.helices[1].id],
            params=BendParams(curvature_deg_per_bp=.1, direction_deg=30))
        operations.insert(0, bend)
        if extra_op == "preceding":
            sweep.params.preceding_op_ids = [bend.id]
    cluster = ClusterRigidTransform(id="placed", helix_ids=[h.id for h in seed.helices],
        translation=[3, -2, 7], rotation=Rotation.from_euler("z", .4).as_quat().tolist())
    return seed.copy_with(deformations=operations, cluster_transforms=[cluster])


def _legacy_samples(design):
    """Independent oracle: exactly the scalar frame sampling used before batching."""
    result = {}
    for helix in design.helices:
        effective = deformation.effective_helix_for_geometry(helix, design)
        arm = [deformation.effective_helix_for_geometry(h, design)
               for h in deformation._arm_helices_for(design, helix.id)]
        centroid, tangent = deformation._bundle_centroid_and_tangent(arm)
        offset = effective.axis_start.to_array() - centroid
        offset -= np.dot(offset, tangent) * tangent
        arm_start = min(h.bp_start for h in arm)
        samples = list(range(0, helix.length_bp, deformation._AXIS_SAMPLE_STEP))
        if samples[-1] != helix.length_bp - 1:
            samples.append(helix.length_bp - 1)
        pre = []
        for bp in samples:
            point, frame, _ = deformation._frame_at_bp(design, bp + helix.bp_start - arm_start, arm)
            pre.append((point + frame @ offset).tolist())
        clusters = deformation._clusters_for_helix(design, helix.id)
        result[helix.id] = [deformation._apply_cluster_transforms_to_point(p, clusters, helix, design) for p in pre]
    return result


@pytest.mark.parametrize("start_bp", [0, 37, -11])
@pytest.mark.parametrize("extra_op", [None, "preceding"])
def test_batched_indexed_axes_preserve_scalar_samples_segments_and_pose(start_bp, extra_op, monkeypatch):
    design = _design(start_bp, extra_op)
    expected = _legacy_samples(design)
    original = sweep_path.sweep_frames
    evaluations = []

    def counted(*args, **kwargs):
        evaluations.append(len(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(sweep_path, "sweep_frames", counted)
    actual = deformation.deformed_helix_axes(design)
    assert len(evaluations) == len(design.helices)
    assert min(evaluations) > 1
    for axis in actual:
        np.testing.assert_allclose(axis["samples"], expected[axis["helix_id"]], rtol=0, atol=1e-12)
        np.testing.assert_allclose(axis["start"], expected[axis["helix_id"]][0], rtol=0, atol=1e-12)
        np.testing.assert_allclose(axis["end"], expected[axis["helix_id"]][-1], rtol=0, atol=1e-12)
        for segment in axis["segments"]:
            np.testing.assert_allclose(segment["start"], axis["start"], rtol=0, atol=1e-12)
            np.testing.assert_allclose(segment["end"], axis["end"], rtol=0, atol=1e-12)


def test_mixed_arm_deformation_keeps_scalar_path_even_if_only_neighbor_has_bend(monkeypatch):
    design = _design(extra_op="active")
    expected = _legacy_samples(design)
    original = sweep_path.sweep_frames
    sample_counts = []

    def counted(*args, **kwargs):
        sample_counts.append(len(args[1]))
        return original(*args, **kwargs)

    monkeypatch.setattr(sweep_path, "sweep_frames", counted)
    actual = deformation.deformed_helix_axes(design)
    assert len(sample_counts) > len(design.helices)
    assert set(sample_counts) == {1}
    for axis in actual:
        np.testing.assert_allclose(axis["samples"], expected[axis["helix_id"]], rtol=0, atol=1e-12)
