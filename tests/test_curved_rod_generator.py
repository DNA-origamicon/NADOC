"""Curved rods use real bend/loop-skip operations, with fixed cargo centers."""

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import state
from backend.api.headless_build import scratch_session
from backend.api.routes_generate_design import generate_design, GenerateRequest
from backend.core.two_np_generator import GeneratorSettings, gold_particles
from backend.core.platform_generator import plan_generated
from backend.core.curved_rod_generator import path_options, physical_scaffold_nt
from backend.core.design_geometry import fitting_geometry
from backend.core.models import Design, Nanoparticle, Mat4x4, LatticeType
from backend.core.validator import validate_design


def source(count=3, lattice=LatticeType.HONEYCOMB):
    particles = []
    for point in [[0.0, 0, 0], [28.0, 0, 0], [28.0, 0, 30], [0.0, 0, 30]][:count]:
        pose = np.eye(4)
        pose[:3, 3] = point
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    return Design(lattice_type=lattice, nanoparticles=particles)


@pytest.mark.slow
def test_orders_and_curved_plan_budget():
    design = source(4)
    settings = GeneratorSettings(shape="curved-rod")
    paths = path_options(design, settings)
    assert len(paths) == 12
    ids = [p.id for p in design.nanoparticles]
    explicit = path_options(design, settings.model_copy(update={"particle_order": ids}))
    assert len(explicit) == 1 and explicit[0]["particle_ids"] == ids
    candidate, report = plan_generated(design, settings)
    assert report["shape"] == "curved-rod"
    assert sorted(report["path_particle_ids"]) == sorted(ids)
    assert candidate.summary["scaffold_used_nt"] <= candidate.summary["scaffold_size"]
    with pytest.raises(ValueError, match="exactly once"):
        path_options(design, settings.model_copy(update={"particle_order": ids[:2]}))


@pytest.mark.slow
def test_curved_generation_native_attachment_geometry_and_history(monkeypatch):
    # Saved v1 generator features retain their original dependent replay editor.
    from functools import partial
    from backend.api import routes_generate_design
    from backend.api.generated_history import build_recorded
    monkeypatch.setattr(routes_generate_design, "build_recorded", partial(build_recorded, standard=False))
    from backend.api.crud import _seek_feature_log, revert_to_before_feature

    original = source()
    _, centers, _ = gold_particles(original)
    with scratch_session():
        state.set_design(original)
        response = generate_design(
            GenerateRequest(shape="curved-rod", expected_revision=state.revision())
        )
        d = state.get_or_404()
        assert validate_design(d).passed
        assert d.deformations
        assert any(h.loop_skips for h in d.helices)
        assert (
            physical_scaffold_nt(d)
            <= response["generation"]["selected"]["scaffold_size"]
        )
        assert len(d.nanoparticle_connection_versions) == 3
        assert all(
            v.relaxed and v.residual_nm < 1e-8
            for v in d.nanoparticle_connection_versions
        )
        np.testing.assert_allclose(
            [p.pose.to_array()[:3, 3] for p in d.nanoparticles], centers, atol=1e-10
        )
        geometry = fitting_geometry(d)
        points = np.array(
            [n[k] for n in geometry for k in ("backbone_position", "base_position")]
        )
        lookup = {
            (n["helix_id"], n["bp_index"], n["direction"]): np.asarray(
                n["backbone_position"]
            )
            for n in geometry
        }
        attachment_helices = {
            o.helix_id
            for o in d.overhangs
            if any(v.overhang_id == o.id for v in d.nanoparticle_connection_versions)
        }
        for crossover in d.crossovers:
            halves = (crossover.half_a, crossover.half_b)
            if any(h.helix_id in attachment_helices for h in halves):
                a, b = [lookup[(h.helix_id, h.index, h.strand.value)] for h in halves]
                assert np.linalg.norm(a - b) < 2.0
        for p, c in zip(d.nanoparticles, centers):
            assert np.min(np.linalg.norm(points - c, axis=1)) >= p.diameter_nm / 2
        for i, entry in enumerate(d.feature_log):
            expected = state.decode_design_snapshot(entry.post_state_gz_b64)
            scrubbed = _seek_feature_log(d, i)
            for field in (
                "helices",
                "deformations",
                "nanoparticles",
                "cluster_transforms",
                "duplexes",
            ):
                assert getattr(scrubbed, field) == getattr(expected, field), (i, field)
        from backend.api.crud import edit_feature, EditFeatureBody

        path_index = next(
            i
            for i, e in enumerate(d.feature_log)
            if e.params["_generator"]["key"] == "curve-path"
        )
        with pytest.raises(HTTPException, match="every particle"):
            edit_feature(path_index, EditFeatureBody(params={"path_order": "1, 1, 3"}))
        with pytest.raises(HTTPException, match="Pathing must be"):
            edit_feature(path_index, EditFeatureBody(params={"pathing": "invalid"}))
        assert state.get_or_404().model_dump() == d.model_dump()
        order = d.feature_log[path_index].params["path_order"].split(",")
        reverse = ", ".join(x.strip() for x in reversed(order))
        edit_feature(path_index, EditFeatureBody(params={"path_order": reverse}))
        edited = state.get_or_404()
        assert edited.feature_log[path_index].params["path_order"] == reverse
        previous_ids = {e.params["_generator"]["key"]: e.id for e in d.feature_log}
        for entry in edited.feature_log:
            key = entry.params["_generator"]["key"]
            if key in previous_ids:
                assert entry.id == previous_ids[key]
        assert validate_design(edited).passed
        np.testing.assert_allclose(
            [p.pose.to_array()[:3, 3] for p in edited.nanoparticles], centers
        )
        mark_index = next(
            i
            for i, e in enumerate(edited.feature_log)
            if e.params["_generator"]["key"] == "curve-marks"
        )
        revert_to_before_feature(mark_index)
        edit_feature(path_index, EditFeatureBody(params={"bend_scale": 0.99}))
        partial = state.get_or_404()
        assert len(partial.feature_log) == mark_index
        assert partial.deformations and not partial.nanoparticle_connection_versions
        assert not any(h.loop_skips for h in partial.helices)
        edit_feature(path_index, EditFeatureBody(params={"pathing": "exterior"}))
        lateral = state.get_or_404()
        assert lateral.feature_log[path_index].params["pathing"] == "exterior"
        assert len(lateral.feature_log) == mark_index
        assert lateral.deformations != partial.deformations
        np.testing.assert_allclose(
            [p.pose.to_array()[:3, 3] for p in lateral.nanoparticles], centers
        )
        revert_to_before_feature(0)
        assert state.get_or_404().model_dump() == original.model_dump()


def test_gentle_curve_accumulates_fractional_insertions():
    from backend.core.curved_rod_generator import encode_curvature
    from backend.core.models import (
        Helix,
        Vec3,
        Strand,
        StrandType,
        Domain,
        Direction,
        DeformationOp,
        BendParams,
    )

    helices = [
        Helix(
            id=f"h{i}",
            axis_start=Vec3(x=x, y=0, z=0),
            axis_end=Vec3(x=x, y=0, z=42.84),
            length_bp=126,
            phase_offset=0,
        )
        for i, x in enumerate([-2.0, 2.0])
    ]
    strands = [
        Strand(
            strand_type=kind,
            domains=[
                Domain(
                    helix_id=h.id,
                    direction=direction,
                    start_bp=0 if direction == Direction.FORWARD else 125,
                    end_bp=125 if direction == Direction.FORWARD else 0,
                )
            ],
        )
        for h in helices
        for kind, direction in [
            (StrandType.SCAFFOLD, Direction.FORWARD),
            (StrandType.STAPLE, Direction.REVERSE),
        ]
    ]
    design = Design(helices=helices, strands=strands)
    ops = [
        DeformationOp(
            type="bend",
            plane_a_bp=a,
            plane_b_bp=a + 7,
            affected_helix_ids=[h.id for h in helices],
            params=BendParams(curvature_deg_per_bp=0.1, direction_deg=0),
        )
        for a in range(7, 112, 7)
    ]
    result = encode_curvature(design, ops)
    # Each window requests only 0.072 bp/helix. Rounding each independently
    # would emit none; the total 10.5-degree bend needs +/-1 bp.
    assert [sum(m.delta for m in h.loop_skips) for h in result.helices] == [1, -1]


def four_particle_arrangement():
    """Particle centers from the user's 4NP_gen_test_aligned arrangement."""
    design = source(4)
    points = [
        [0, 0, 0],
        [56.40551466176245, 0, 0],
        [-7.551554339318557, 0, 40.35936867659473],
        [71.42239405775832, 0, 29.964042899176135],
    ]
    for p, point in zip(design.nanoparticles, points):
        pose = p.pose.to_array()
        pose[:3, 3] = point
        p.pose = Mat4x4.from_array(pose)
    return design


@pytest.mark.parametrize("mode", ["colocalized", "interior", "exterior"])
def test_complete_intermediate_sections_improve_user_arrangement(mode):
    from backend.core.two_np_generator import cross_sections

    design = four_particle_arrangement()
    candidate, report = plan_generated(
        design, GeneratorSettings(shape="curved-rod", pathing=mode)
    )
    six = next(s for s in cross_sections(design.lattice_type) if s["helix_count"] == 6)
    assert candidate.summary["helix_count"] >= 10
    assert candidate.summary["section_score"] > six["section_score"]
    assert candidate.summary["scaffold_used_nt"] <= candidate.summary["scaffold_size"]
    centers = np.array(report["centers_nm"])
    path_points = np.array(candidate.summary["path"]["station_points_world"])
    if mode == "colocalized":
        np.testing.assert_allclose(path_points, centers, atol=1e-10)
    else:
        radial = centers - centers.mean(0)
        dot = np.sum((path_points - centers) * radial, axis=1)
        assert np.all(dot < 0) if mode == "interior" else np.all(dot > 0)
        np.testing.assert_allclose(path_points[:, 1], centers[:, 1], atol=1e-10)


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["interior", "exterior"])
def test_lateral_routes_attach_at_fixed_centers_without_gold_core_collisions(mode):
    from backend.api.two_np_build import materialize

    original = four_particle_arrangement()
    settings = GeneratorSettings(shape="curved-rod", pathing=mode)
    candidate, _ = plan_generated(original, settings)
    with scratch_session():
        generated, report = materialize(original, candidate, settings)
        assert validate_design(generated).passed
        assert max(report["attachment_residuals_nm"]) < 1e-8
        _, centers, _ = gold_particles(original)
        np.testing.assert_allclose(
            [p.pose.to_array()[:3, 3] for p in generated.nanoparticles], centers
        )
        points = np.array(
            [
                n[k]
                for n in fitting_geometry(generated)
                for k in ("backbone_position", "base_position")
            ]
        )
        for p, center in zip(original.nanoparticles, centers):
            assert np.min(np.linalg.norm(points - center, axis=1)) >= p.diameter_nm / 2
