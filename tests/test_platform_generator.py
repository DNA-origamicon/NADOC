"""Solid-platform coverage, fixed-center attachments, and recorded construction."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from fastapi import HTTPException

from backend.api import state
from backend.api.headless_build import scratch_session
from backend.api.routes_generate_design import generate_design, GenerateRequest
from backend.core.models import Design, LatticeType, Mat4x4, Nanoparticle
from backend.core.platform_generator import platform_frame, plan_generated
from backend.core.two_np_generator import GeneratorSettings, gold_particles, scaffold_nt
from backend.core.design_geometry import fitting_geometry
from backend.core.duplex import duplex_wc_ok
from backend.core.protein import resolve_overhang_anchor
from backend.core.validator import validate_design


def platform_source(count=3, lattice=LatticeType.HONEYCOMB, heights=None):
    points = np.array([[0.0, 0, 0], [24.0, 0, 0], [0.0, 0, 28], [24.0, 0, 28]])[:count]
    if heights is not None:
        points[:, 1] = heights
    rotation = Rotation.from_euler("xyz", [29, -38, 17], degrees=True).as_matrix()
    particles = []
    for point in points:
        pose = np.eye(4)
        pose[:3, 3] = rotation @ point + [17, -13, 9]
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    return Design(lattice_type=lattice, nanoparticles=particles)


@pytest.mark.parametrize("count", [3, 4])
@pytest.mark.parametrize("lattice", list(LatticeType))
def test_platform_plan_complete_layers_and_budget(count, lattice):
    original = platform_source(count, lattice)
    before = original.model_dump_json()
    candidate, report = plan_generated(original, GeneratorSettings())
    summary = candidate.summary
    assert report["shape"] == "platform"
    assert report["plane_deviation_nm"] < 1e-9
    cells = {tuple(c) for c in summary["cells"]}
    assert cells == {
        (r, c) for r in {p[0] for p in cells} for c in {p[1] for p in cells}
    }
    assert (
        scaffold_nt(candidate.design)
        == summary["scaffold_used_nt"]
        <= summary["scaffold_size"]
    )
    assert len(candidate.design.scaffolds()) == 1
    alternatives = [x for x in report["alternatives"] if x.get("feasible", True)]
    if summary["scaffold_size"] == 8064 and len(alternatives) == 2:
        assert alternatives[1]["layers"] > alternatives[0]["layers"]
    assert original.model_dump_json() == before


def test_plane_nonplanarity_rotation_and_collinear_rejection():
    _, centers, _ = gold_particles(platform_source(4, heights=[0, 0, 0, 3]))
    frame = platform_frame(centers)
    rotated = platform_frame(centers, 37)
    np.testing.assert_allclose(frame.T @ frame, np.eye(3), atol=1e-12)
    assert np.linalg.det(frame) == pytest.approx(1)
    np.testing.assert_allclose(frame[:, 1], rotated[:, 1])
    assert not np.allclose(frame[:, 2], rotated[:, 2])
    assert np.max(np.abs((centers - centers.mean(0)) @ frame[:, 1])) > 0.1
    with pytest.raises(ValueError, match="non-collinear"):
        platform_frame(np.array([[0.0, 0, 0], [10.0, 0, 0], [20.0, 0, 0]]))


@pytest.mark.slow
@pytest.mark.parametrize(
    "count,lattice,heights",
    [
        (3, LatticeType.HONEYCOMB, None),
        (4, LatticeType.SQUARE, [0, 0, 0, 2]),
    ],
)
def test_platform_generation_fixed_centers_native_geometry_and_history(
    count, lattice, heights
):
    from backend.api.crud import _seek_feature_log, revert_to_before_feature

    original = platform_source(count, lattice, heights)
    _, centers, _ = gold_particles(original)
    with scratch_session(lattice):
        state.set_design(original)
        response = generate_design(GenerateRequest(expected_revision=state.revision()))
        design = state.get_or_404()
        assert validate_design(design).passed
        assert len(response["generation"]["connections"]) == count
        assert len(design.nanoparticle_connection_versions) == count
        assert all(duplex_wc_ok(design, dx)[0] for dx in design.duplexes)
        assert all(
            v.applied and v.relaxed and v.residual_nm < 1e-8
            for v in design.nanoparticle_connection_versions
        )
        assert (
            len(
                {
                    design.find_strand(v.strand_id).sequence
                    for v in design.nanoparticle_connection_versions
                }
            )
            == count
        )
        geometry = fitting_geometry(design)
        positions = np.array(
            [n[key] for n in geometry for key in ("backbone_position", "base_position")]
        )
        normal = np.array(response["generation"]["side_normal"])
        for particle, center, version in zip(
            design.nanoparticles, centers, design.nanoparticle_connection_versions
        ):
            np.testing.assert_allclose(
                particle.pose.to_array()[:3, 3], center, atol=1e-10
            )
            assert (
                np.min(np.linalg.norm(positions - center, axis=1))
                >= particle.diameter_nm / 2
            )
            root, _ = resolve_overhang_anchor(geometry, version.overhang_id, "root")
            assert np.dot(center - root, normal) > 0
        assert all(e.op_kind != "generate-design" for e in design.feature_log)
        for i, entry in enumerate(design.feature_log):
            expected = state.decode_design_snapshot(entry.post_state_gz_b64)
            scrubbed = _seek_feature_log(design, i)
            for field in (
                "helices",
                "strands",
                "nanoparticles",
                "duplexes",
                "nanoparticle_connection_versions",
                "cluster_transforms",
            ):
                assert getattr(scrubbed, field) == getattr(expected, field), (i, field)
        revert_to_before_feature(0)
        assert state.get_or_404().model_dump() == original.model_dump()


@pytest.mark.slow
def test_four_particle_honeycomb_platform_edit_replays_at_fixed_centers():
    from backend.api.crud import edit_feature, EditFeatureBody

    original = platform_source(4)
    _, centers, _ = gold_particles(original)
    with scratch_session():
        state.set_design(original)
        generate_design(GenerateRequest(expected_revision=state.revision()))
        before = state.get_or_404()
        index = next(
            i
            for i, e in enumerate(before.feature_log)
            if e.params.get("_generator", {}).get("key") == "rod-pose"
        )
        edit_feature(index, EditFeatureBody(params={"roll_deg": 5}))
        edited = state.get_or_404()
        assert validate_design(edited).passed
        assert edited.feature_log[index].params["roll_deg"] == 5
        original_ids = {e.params["_generator"]["key"]: e.id for e in before.feature_log}
        # A new orientation can require different nick operations. Surviving
        # commands retain identity even if new nicks shift their row positions.
        for entry in edited.feature_log:
            key = entry.params["_generator"]["key"]
            if key in original_ids:
                assert entry.id == original_ids[key]
        for particle, center in zip(edited.nanoparticles, centers):
            np.testing.assert_allclose(
                particle.pose.to_array()[:3, 3], center, atol=1e-10
            )
        cluster = next(
            c for c in edited.cluster_transforms if c.name == "Generated platform"
        )
        np.testing.assert_allclose(
            Rotation.from_quat(cluster.rotation).as_matrix(),
            platform_frame(centers, 5),
            atol=1e-10,
        )
        assert all(
            v.applied and v.relaxed and v.residual_nm < 1e-8
            for v in edited.nanoparticle_connection_versions
        )


@pytest.mark.slow
def test_unreachable_nonplanar_platform_keeps_design_and_history_unchanged():
    original = platform_source(4, LatticeType.SQUARE, [-20, 20, 20, -20])
    with scratch_session(LatticeType.SQUARE):
        state.set_design(original)
        revision = state.revision()
        with pytest.raises(HTTPException) as error:
            generate_design(GenerateRequest(expected_revision=revision))
        assert error.value.status_code == 422
        assert "cannot all be reached" in str(error.value.detail)
        assert state.revision() == revision
        assert state.get_or_404().model_dump() == original.model_dump()
