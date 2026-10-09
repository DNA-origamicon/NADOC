"""Attachment is atomic, sequence-aware and independently checks emitted geometry."""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api import state
from backend.api.main import app
from backend.api.nanoparticle_attachment import attach_nanoparticle
from backend.core.models import (
    Design,
    Direction,
    Domain,
    Helix,
    OverhangSpec,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.nanoparticle_attachment_obstacles import particle_clearance
from backend.core.design_geometry import fitting_geometry

client = TestClient(app)


@pytest.fixture
def attachment_source():
    helix = Helix(
        id="target",
        axis_start=Vec3(x=14, y=3, z=0),
        axis_end=Vec3(x=14, y=3, z=5.78),
        length_bp=18,
    )
    sequence = "GGCGACTGTGCTACTTAT"
    strand = Strand(
        id="target-strand",
        domains=[
            Domain(
                helix_id=helix.id,
                start_bp=0,
                end_bp=17,
                direction=Direction.FORWARD,
                overhang_id="target_3p",
            )
        ],
        strand_type=StrandType.STAPLE,
        sequence=sequence,
    )
    state.set_design(
        Design(
            helices=[helix],
            strands=[strand],
            overhangs=[
                OverhangSpec(
                    id="target_3p",
                    helix_id=helix.id,
                    strand_id=strand.id,
                    sequence=sequence,
                )
            ],
        )
    )
    particle_id = client.post(
        "/api/design/nanoparticles/gold-nanospheres", json={"diameter_nm": 10}
    ).json()["nanoparticle_id"]
    result = client.put(
        f"/api/design/nanoparticles/{particle_id}/conjugation",
        json={
            "scheme": "direct_thiol",
            "sequence": "ATAAGTAGCACAGTCGCC",
            "count": 1,
            "attach_end": "5p",
            "seed": 3,
        },
    )
    assert result.status_code == 200, result.text
    yield state.get_design().model_copy(deep=True), particle_id
    state.close_session()


def request(particle_id, **overrides):
    design, revision = state.copy_for_persist()
    return client.post(
        f"/api/design/nanoparticles/{particle_id}/attach-overhang",
        json={
            "overhang_id": "target_3p",
            "expected_design_id": design.id,
            "expected_revision": revision,
            **overrides,
        },
    )


def test_atomic_attach_closes_native_joint_and_records_one_feature(attachment_source):
    before, pid = attachment_source
    result = request(pid)
    assert result.status_code == 200, result.text
    after = state.get_design()
    assert len(after.feature_log) == len(before.feature_log) + 1
    assert after.feature_log[-1].op_kind == "nanoparticle-attach-overhang"
    assert after.nanoparticle_connection_versions[0].residual_nm < 0.02
    assert particle_clearance(after, fitting_geometry(after), pid) >= -1e-6
    assert (
        before.nanoparticle_conjugations[0].surface_strands[0].strand_id
        == after.nanoparticle_connection_versions[0].strand_id
    )
    assert (
        after.find_strand("target-strand").sequence
        == before.find_strand("target-strand").sequence
    )
    replayed = state.decode_design_snapshot(after.feature_log[-1].post_state_gz_b64)
    assert replayed.duplexes == after.duplexes
    assert replayed.cluster_transforms == after.cluster_transforms
    duplicate = request(pid)
    assert duplicate.status_code == 422
    assert state.get_design() == after


def test_infeasible_locked_center_does_not_mutate(attachment_source):
    before, pid = attachment_source
    result = request(pid, fixed_center=True)
    assert result.status_code == 422, result.text
    assert state.get_design() == before


def test_stale_revision_and_incompatible_sequence_do_not_mutate(attachment_source):
    before, pid = attachment_source
    assert request(pid, expected_revision=-1).status_code == 409
    invalid = before.copy_with(
        overhangs=[before.overhangs[0].model_copy(update={"sequence": "A" * 18})]
    )
    with pytest.raises(ValueError, match="complementary"):
        attach_nanoparticle(invalid, pid, "target_3p")
    assert state.get_design() == before


def test_fixed_center_kernel_preserves_translation():
    from backend.core.nanoparticle_kinematics import solve_closed_loop_pose

    pose, report = solve_closed_loop_pose(
        np.eye(4),
        np.array([[2.0, 0, 0]]),
        np.array([[-8.0, 0, 0]]),
        np.array([10.0]),
        np.empty((0, 3)),
        0,
        fixed_center=True,
    )
    assert report["converged"]
    assert np.array_equal(pose[:3, 3], np.zeros(3))


def test_rebind_after_unapply_preserves_fixed_center(attachment_source):
    from backend.api.routes_nanoparticles import _set_np_version_applied

    source, pid = attachment_source
    attached, report = attach_nanoparticle(source, pid, "target_3p")
    unbound = _set_np_version_applied(attached, report["version_id"], False)
    rebound, measured = attach_nanoparticle(
        unbound, pid, "target_3p", fixed_center=True
    )
    assert measured["residual_nm"] < 0.02
    assert np.array_equal(
        rebound.nanoparticles[0].pose.to_array()[:3, 3],
        attached.nanoparticles[0].pose.to_array()[:3, 3],
    )


def test_other_particle_radius_is_an_obstacle():
    from backend.core.nanoparticle_kinematics import solve_closed_loop_pose

    pose, report = solve_closed_loop_pose(
        np.eye(4),
        np.array([[2.0, 0, 0]]),
        np.array([[-8.0, 0, 0]]),
        np.array([10.0]),
        np.array([[0.0, 0, 0]]),
        4.0,
        obstacle_radii=np.array([3.0]),
    )
    assert report["max_penetration_nm"] <= 0.05
    assert np.linalg.norm(pose[:3, 3]) >= 6.95


@pytest.mark.parametrize("edit", [False, True])
def test_concurrent_save_allowed_but_design_edit_rejected(
    attachment_source, monkeypatch, edit
):
    from backend.api import routes_nanoparticle_attachment as route
    from backend.core.models import DesignLoadout

    source, pid = attachment_source
    source = source.copy_with(
        loadouts=[DesignLoadout(id="main")], active_loadout_id="main"
    )
    state.set_design(source)
    original = route.attach_nanoparticle

    def fit(*args, **kwargs):
        fitted = original(*args, **kwargs)
        current, revision = state.copy_for_persist()
        saved = current.model_copy(deep=True)
        saved.metadata.identity_confirmed_at = "concurrent-save"
        saved.loadouts[0].head_revision_id = "new-head"
        payload, size = state.encode_design_snapshot(current)
        saved.loadouts[0].design_snapshot_gz_b64 = payload
        saved.loadouts[0].snapshot_size_bytes = size
        if edit:
            saved.overhangs[0].sequence = "A" * 18
        state.acknowledge_workspace_save(current, saved, revision)
        return fitted

    monkeypatch.setattr(route, "attach_nanoparticle", fit)
    response = request(pid)
    assert response.status_code == (409 if edit else 200), response.text
    after = state.get_design()
    assert after.metadata.identity_confirmed_at == "concurrent-save"
    assert after.loadouts[0].head_revision_id == "new-head"
    assert len(after.feature_log) == len(source.feature_log) + (not edit)
