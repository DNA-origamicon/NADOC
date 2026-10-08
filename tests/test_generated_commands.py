"""Generation must leave native editable operations, not a bespoke feature language."""

import numpy as np
import pytest
from backend.api import state
from backend.api.headless_build import scratch_session
from backend.api.generated_history import build_recorded
from backend.api.crud import _seek_feature_log
from backend.core.models import Design, Nanoparticle, Mat4x4
from backend.core.two_np_generator import GeneratorSettings
from backend.core.platform_generator import plan_generated


def source():
    particles = []
    for point in [(0, 0, 0), (40, 0, 0), (40, 0, 45)]:
        pose = np.eye(4)
        pose[:3, 3] = point
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    return Design(nanoparticles=particles)


@pytest.fixture(scope="module")
def construction():
    original = source()
    settings = GeneratorSettings(shape="curved-rod")
    candidate, _ = plan_generated(original, settings)
    with scratch_session():
        result, report = build_recorded(original, candidate, settings)
    return original, result, report


def test_native_operations_and_snapshot_boundaries(construction):
    original, design, report = construction
    assert report["connections"]
    assert any(e.feature_type == "deformation" for e in design.feature_log)
    assert any(e.feature_type == "cluster_op" for e in design.feature_log)
    assert any(e.feature_type == "routing-cluster" for e in design.feature_log)
    for e in design.feature_log:
        assert getattr(e, "op_kind", "") not in (
            "curve-path",
            "cluster-pose",
            "nanoparticle-connection-relax",
        )
    for i, entry in enumerate(design.feature_log):
        scrubbed = _seek_feature_log(design, i)
        if entry.feature_type == "deformation":
            assert entry.deformation_id in {op.id for op in scrubbed.deformations}
        if entry.feature_type == "cluster_create":
            assert entry.cluster_id in {c.id for c in scrubbed.cluster_transforms}
            created = next(
                c for c in scrubbed.cluster_transforms if c.id == entry.cluster_id
            )
            assert created.parent_cluster_id == entry.cluster_snapshot.parent_cluster_id
            assert (
                created.overhang_duplex_driver_id
                == entry.cluster_snapshot.overhang_duplex_driver_id
            )
        if not getattr(entry, "post_state_gz_b64", ""):
            continue
        expected = state.decode_design_snapshot(entry.post_state_gz_b64)
        for field in (
            "helices",
            "strands",
            "nanoparticles",
            "deformations",
            "cluster_transforms",
            "duplexes",
        ):
            assert getattr(scrubbed, field) == getattr(expected, field), (
                i,
                getattr(entry, "label", ""),
                field,
            )
    np.testing.assert_allclose(
        [p.pose.values[3::4][:3] for p in design.nanoparticles],
        [p.pose.values[3::4][:3] for p in original.nanoparticles],
    )


def test_ordinary_bend_editor_and_revert(construction):
    from backend.api.crud import edit_feature, EditFeatureBody, revert_to_before_feature

    original, design, _ = construction
    index = next(
        i for i, e in enumerate(design.feature_log) if e.feature_type == "deformation"
    )
    with scratch_session():
        state.set_design(design)
        revert_to_before_feature(index + 1)
        op = state.get_or_404().feature_log[index].op_snapshot
        edited_params = op.params.model_dump()
        edited_params["curvature_deg_per_bp"] *= 0.99
        edit_feature(
            index,
            EditFeatureBody(
                params={
                    "type": "bend",
                    "plane_a_bp": op.plane_a_bp,
                    "plane_b_bp": op.plane_b_bp,
                    "params": edited_params,
                    "affected_helix_ids": op.affected_helix_ids,
                }
            ),
        )
        assert (
            state.get_or_404().deformations[-1].params.curvature_deg_per_bp
            == edited_params["curvature_deg_per_bp"]
        )
        revert_to_before_feature(0)
        assert state.get_or_404().helices == original.helices
        assert state.get_or_404().nanoparticles == original.nanoparticles
