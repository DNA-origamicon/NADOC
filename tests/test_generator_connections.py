"""Real multi-anchor construction: count, native geometry, history and validation."""

from collections import Counter

import numpy as np
import pytest
from pydantic import ValidationError

from backend.api.generated_history import build_recorded
from backend.core.design_geometry import fitting_geometry
from backend.core.nanoparticle_attachment_fit import attachment_joint
from backend.core.models import LatticeType
from backend.core.platform_generator import plan_generated
from backend.core.two_np_generator import GeneratorSettings
from backend.core.validator import validate_design
from tests.test_two_np_generator import source as rod_source
from tests.test_curved_rod_generator import source as multi_source


@pytest.mark.parametrize("count", [0, 4, 1.5, True, "3"])
def test_connection_count_is_bounded_integer(count):
    with pytest.raises(ValidationError):
        GeneratorSettings(connections_per_particle=count)


def test_existing_handles_are_reused_once_before_creating_missing_handles():
    from backend.api.two_np_build import _handles
    from backend.core.models import Design, OverhangSpec
    from backend.core.nanoparticle import build_thiol_conjugation

    source = rod_source()
    for particle in source.nanoparticles:
        owner, helices, strands = build_thiol_conjugation(
            particle, scheme="direct_thiol", sequence="ACGTGACTCAGTACGATC", count=2,
        )
        source = source.copy_with(
            nanoparticle_conjugations=[*source.nanoparticle_conjugations, owner],
            helices=[*source.helices, *helices], strands=[*source.strands, *strands],
            overhangs=[*source.overhangs, *[
                OverhangSpec(id=r.overhang_id, helix_id=r.helix_id, strand_id=r.strand_id,
                             sequence=owner.sequence, auxiliary_endpoint=True)
                for r in owner.surface_strands
            ]],
        )
    _, handles = _handles(source, Design(), source.nanoparticles, GeneratorSettings(connections_per_particle=3))
    assert len(handles) == 6
    assert sum(reused for _, _, _, reused in handles) == 4
    assert len({record.strand_id for _, record, _, _ in handles}) == 6


@pytest.mark.slow
@pytest.mark.parametrize("shape,lattice,count", [
    ("auto", LatticeType.HONEYCOMB, 2),
    ("auto", LatticeType.HONEYCOMB, 3),
    ("auto", LatticeType.SQUARE, 3),
    ("platform", LatticeType.HONEYCOMB, 3),
    ("curved-rod", LatticeType.HONEYCOMB, 3),
])
def test_multiple_connections_close_without_moving_centers(shape, lattice, count):
    source = rod_source(lattice) if shape == "auto" else multi_source(lattice=lattice)
    before = source.model_dump_json()
    settings = GeneratorSettings(shape=shape, connections_per_particle=count)
    candidate, _ = plan_generated(source, settings)
    generated, report = build_recorded(source, candidate, settings)
    assert source.model_dump_json() == before
    assert validate_design(generated).passed
    assert Counter(c["particle_id"] for c in report["connections"]) == {
        p.id: count for p in source.nanoparticles
    }
    assert len({c["strand_id"] for c in report["connections"]}) == count * len(source.nanoparticles)
    assert len({c["overhang_id"] for c in report["connections"]}) == count * len(source.nanoparticles)
    geometry = fitting_geometry(generated)
    for particle, original in zip(generated.nanoparticles, source.nanoparticles):
        np.testing.assert_array_equal(particle.pose.to_array()[:3, 3], original.pose.to_array()[:3, 3])
        joints = []
        for version in generated.nanoparticle_connection_versions:
            if version.applied and version.nanoparticle_id == particle.id:
                joint, local = attachment_joint(generated, version, geometry)
                expected = (particle.pose.to_array() @ np.r_[local, 1])[:3]
                assert np.linalg.norm(joint - expected) < 0.02
                joints.append(joint)
        for i, joint in enumerate(joints):
            assert all(np.linalg.norm(joint - other) > 0.5 for other in joints[i + 1:])
    attachments = [e for e in generated.feature_log if getattr(e, "op_kind", None) == "nanoparticle-attach-overhang"]
    assert len(attachments) == count * len(source.nanoparticles)
    # Native post-state snapshots retain the fitted graft sites and closed joints.
    from backend.api.state import decode_design_snapshot
    restored = decode_design_snapshot(attachments[-1].post_state_gz_b64)
    assert restored.nanoparticle_conjugations == generated.nanoparticle_conjugations

    if shape == "auto" and lattice == LatticeType.HONEYCOMB and count == 3:
        from backend.api.nanoparticle_attachment import attach_nanoparticle
        from backend.api.routes_nanoparticles import _set_np_version_applied
        last = generated.nanoparticle_connection_versions[-1]
        unbound = _set_np_version_applied(generated, last.id, False)
        rebound, measured = attach_nanoparticle(
            unbound, last.nanoparticle_id, last.overhang_id,
            strand_id=last.strand_id, fixed_center=True,
        )
        assert measured["residual_nm"] < 0.02
        assert sum(v.applied for v in rebound.nanoparticle_connection_versions) == 6


@pytest.mark.slow
def test_four_particle_platform_supports_twelve_connections():
    source = multi_source(count=4)
    settings = GeneratorSettings(shape="platform", connections_per_particle=3)
    candidate, _ = plan_generated(source, settings)
    generated, report = build_recorded(source, candidate, settings)
    assert len(report["connections"]) == 12
    assert max(report["attachment_residuals_nm"]) < 0.02
    assert validate_design(generated).passed


@pytest.mark.slow
def test_curved_multivalent_roots_stay_near_particle_station():
    """Uneven four-NP arrangement: the third root used to jump to a far outer helix."""
    from backend.core.models import Design, Mat4x4, Nanoparticle
    from backend.core.generator_validation import check_generated_structure

    centers = [
        (55.79385202856456, 0.8292242807314132, 24.664173753666898),
        (15.0, 0.0, 0.0),
        (45.52394020453521, 1.4550969390152275, -24.501716492961933),
        (24.41251812556016, 0.0, 22.657095855423982),
    ]
    particles = []
    for center in centers:
        pose = np.eye(4)
        pose[:3, 3] = center
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    source = Design(lattice_type=LatticeType.HONEYCOMB, nanoparticles=particles)
    settings = GeneratorSettings(shape="curved-rod", connections_per_particle=3)
    candidate, _ = plan_generated(source, settings)
    generated, report = build_recorded(source, candidate, settings)
    assert len(report["connections"]) == 12
    assert max(report["attachment_residuals_nm"]) < 0.02
    for particle, center in zip(generated.nanoparticles, centers):
        np.testing.assert_array_equal(particle.pose.to_array()[:3, 3], center)
    assert validate_design(generated).passed
    assert check_generated_structure(generated, report["generated_helix_ids"])["status"] == "passed"


@pytest.mark.slow
def test_unreachable_extra_connections_leave_design_unchanged():
    from fastapi import HTTPException
    from backend.api import state
    from backend.api.headless_build import scratch_session
    from backend.api.routes_generate_design import generate_design, GenerateRequest
    from tests.test_generator_mechanics import source as wide_source

    # This interior path supports the original single anchors, but the third
    # legal root lies outside an 18 bp duplex's fixed-center reach.
    with scratch_session():
        original = wide_source()
        state.set_design(original)
        revision = state.revision()
        with pytest.raises(HTTPException) as error:
            generate_design(GenerateRequest(expected_revision=revision,
                shape="curved-rod", pathing="interior", connections_per_particle=3))
        assert error.value.status_code == 422
        assert "spheres do not intersect" in error.value.detail
        assert state.revision() == revision
        assert state.get_or_404() == original
