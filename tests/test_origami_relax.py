"""Geometric fit contract, independently checked against rendered endpoints."""

import numpy as np
import pytest
from backend.core.models import Design, Helix, Vec3, Strand, Domain, Direction
from backend.core.origami_relax import relax_origami, stretch_summary
from backend.core.design_geometry import _geometry_for_design


def fixture():
    return Design(
        helices=[
            Helix(
                id="a",
                grid_pos=(0, 0),
                axis_start=Vec3(x=0, y=0, z=0),
                axis_end=Vec3(x=0, y=0, z=10),
                length_bp=31,
            ),
            Helix(
                id="b",
                grid_pos=(10, 0),
                axis_start=Vec3(x=0, y=20, z=0),
                axis_end=Vec3(x=0, y=20, z=10),
                length_bp=31,
            ),
        ],
        strands=[
            Strand(
                domains=[
                    Domain(
                        helix_id="a", start_bp=0, end_bp=30, direction=Direction.FORWARD
                    ),
                    Domain(
                        helix_id="b", start_bp=30, end_bp=0, direction=Direction.REVERSE
                    ),
                ]
            )
        ],
    )


def test_stretch_summary():
    assert stretch_summary(np.array([0.0, 3.0, 4.0])) == {
        "max_excess_nm": 4.0,
        "rms_bond_error_nm": float(np.sqrt(25 / 3)),
        "stretched_bonds": 2,
    }


def test_relaxes_real_endpoints_without_changing_topology_or_input():
    design = fixture()
    original = design.model_dump()
    relaxed, report = relax_origami(design, max_steps=500)
    assert design.model_dump() == original
    assert relaxed.strands == design.strands
    assert relaxed.helices == design.helices
    assert relaxed.crossovers == design.crossovers
    g = _geometry_for_design(relaxed)
    a = next(n for n in g if n["helix_id"] == "a" and n["bp_index"] == 30)
    b = next(n for n in g if n["helix_id"] == "b" and n["bp_index"] == 30)
    excess = max(
        np.linalg.norm(np.array(a["backbone_position"]) - b["backbone_position"])
        - 0.67,
        0,
    )
    assert excess < 1.0
    assert report["after"]["max_excess_nm"] == pytest.approx(excess, abs=1e-7)
    assert report["planar"]
    reloaded = Design.model_validate_json(relaxed.to_json())
    assert reloaded.cluster_transforms == relaxed.cluster_transforms


def test_rejects_no_bonds():
    design = fixture().copy_with(strands=[])
    with pytest.raises(ValueError):
        relax_origami(design)


def test_route_records_one_undoable_step_and_does_not_retry_topology(monkeypatch):
    from backend.api import state
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.api.routes_origami_relax import relax

    token = set_current_doc("origami-relax-unit")
    try:
        design = fixture()
        state.load_design(design)

        def forbidden(*args):
            raise AssertionError("Pose relaxation must not retry pending ligations")

        monkeypatch.setattr(state, "_retry_pending_ligations", forbidden)
        response = relax()
        assert response["relaxation"]["after"]["max_excess_nm"] < 1
        current = state.get_or_404()
        assert current.feature_log[-1].op_kind == "relax-origami"
        assert current.strands == design.strands
        assert len(state._session().history) == 1
        restored = state.decode_design_snapshot(
            current.feature_log[-1].design_snapshot_gz_b64
        )
        assert restored.cluster_transforms == design.cluster_transforms
    finally:
        state.close_session()
        reset_current_doc(token)


def test_extra_base_contour_is_slack_not_a_spring_that_pulls_ends_apart():
    from backend.core.models import ForcedLigation

    design = fixture().copy_with(
        forced_ligations=[
            ForcedLigation(
                three_prime_helix_id="a",
                three_prime_bp=30,
                three_prime_direction=Direction.FORWARD,
                five_prime_helix_id="b",
                five_prime_bp=30,
                five_prime_direction=Direction.REVERSE,
                extra_bases="T" * 40,
            )
        ]
    )
    relaxed, report = relax_origami(design, max_steps=100)
    assert report["before"]["max_excess_nm"] == 0
    assert report["after"]["max_excess_nm"] == 0
    assert all(np.allclose(c.translation, 0) for c in relaxed.cluster_transforms)


@pytest.mark.parametrize("geometry_change", [False, True])
def test_concurrent_view_update_survives_but_pose_edit_rejects(
    monkeypatch, geometry_change
):
    from fastapi import HTTPException
    from backend.api import state, routes_origami_relax as route
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.core.models import CameraPose, ClusterRigidTransform

    token = set_current_doc("origami-relax-concurrent-unit")
    try:
        design = fixture()
        state.load_design(design)
        solve = route.relax_origami

        def concurrent(source):
            result = solve(source, max_steps=100)
            update = {"camera_poses": [CameraPose(name="Review")]}
            if geometry_change:
                update["cluster_transforms"] = [
                    ClusterRigidTransform(helix_ids=["b"], translation=[0, 2, 0])
                ]
            state.set_design(source.copy_with(**update))
            return result

        monkeypatch.setattr(route, "relax_origami", concurrent)
        if geometry_change:
            with pytest.raises(HTTPException) as error:
                route.relax()
            assert error.value.status_code == 409
            assert state.get_or_404().cluster_transforms[0].translation == [0, 2, 0]
            assert not state.get_or_404().feature_log
        else:
            route.relax()
            assert state.get_or_404().camera_poses[0].name == "Review"
            assert state.get_or_404().feature_log[-1].op_kind == "relax-origami"
    finally:
        state.close_session()
        reset_current_doc(token)


def test_second_attempt_does_not_relabel_remaining_stretch_as_rest_length():
    relaxed, first = relax_origami(fixture(), max_steps=100)
    _, second = relax_origami(relaxed, max_steps=100)
    assert second["before"]["max_excess_nm"] == pytest.approx(
        first["after"]["max_excess_nm"], abs=1e-7
    )


@pytest.mark.parametrize("existing_branch", [False, True])
def test_first_autosave_loadout_is_safe_but_branch_switch_is_not(
    monkeypatch, existing_branch
):
    from fastapi import HTTPException
    from backend.api import state, routes_origami_relax as route
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.core.design_loadouts import ensure_loadouts
    from backend.core.models import DesignLoadout

    token = set_current_doc("origami-relax-loadout-unit")
    try:
        design = fixture()
        if existing_branch:
            loadouts, active = ensure_loadouts(design)
            design = design.copy_with(loadouts=loadouts, active_loadout_id=active)
        state.load_design(design)
        solve = route.relax_origami

        def concurrent(source):
            result = solve(source, max_steps=100)
            loadouts, active = ensure_loadouts(source)
            if existing_branch:
                branch = DesignLoadout(name="Another branch")
                loadouts.append(branch)
                active = branch.id
            state.set_design(
                source.copy_with(loadouts=loadouts, active_loadout_id=active)
            )
            return result

        monkeypatch.setattr(route, "relax_origami", concurrent)
        if existing_branch:
            with pytest.raises(HTTPException) as error:
                route.relax()
            assert error.value.status_code == 409
        else:
            route.relax()
            assert len(state.get_or_404().loadouts) == 1
            assert (
                state.get_or_404().active_loadout_id
                == state.get_or_404().loadouts[0].id
            )
    finally:
        state.close_session()
        reset_current_doc(token)


def test_preserves_whole_body_geometry_and_composes_existing_poses():
    from backend.core.models import ClusterRigidTransform
    from scipy.spatial.distance import pdist
    from scipy.spatial.transform import Rotation

    design = fixture()
    c = design.helices[0].model_copy(
        update={
            "id": "c",
            "grid_pos": (1, 0),
            "axis_start": Vec3(x=0, y=2, z=0),
            "axis_end": Vec3(x=0, y=2, z=10),
        }
    )
    strand = Strand(
        domains=[
            Domain(helix_id="c", start_bp=0, end_bp=30, direction=Direction.FORWARD)
        ]
    )
    design = design.copy_with(
        helices=[*design.helices, c],
        strands=[*design.strands, strand],
        cluster_transforms=[
            ClusterRigidTransform(helix_ids=["b"]),
            ClusterRigidTransform(
                helix_ids=["a", "c"],
                pivot=[1, 2, 3],
                translation=[0, -3, 1],
                rotation=Rotation.from_rotvec([0.2, 0, 0]).as_quat().tolist(),
            ),
        ],
    )
    before = _geometry_for_design(design)
    relaxed, report = relax_origami(design, max_steps=500)
    after = _geometry_for_design(relaxed)
    for body in design.cluster_transforms:

        def points(geometry):
            return [
                b["backbone_position"]
                for b in geometry
                if b["helix_id"] in body.helix_ids
            ]

        assert np.allclose(pdist(points(before)), pdist(points(after)), atol=1e-8)
    assert [c.id for c in relaxed.cluster_transforms] == [
        c.id for c in design.cluster_transforms
    ]
    assert report["bond_count"] == 1
    repeated, second = relax_origami(relaxed, max_steps=100)
    assert len(repeated.cluster_transforms) == 2
    assert second["before"] == pytest.approx(report["after"], abs=1e-7)


def test_never_splits_a_single_explicit_body():
    from backend.core.models import ClusterRigidTransform

    design = fixture().copy_with(
        cluster_transforms=[ClusterRigidTransform(helix_ids=["a", "b"])]
    )
    with pytest.raises(ValueError, match="Only one rigid cluster"):
        relax_origami(design)


def test_default_umbrella_is_replaced_by_detected_bodies():
    from backend.core.cluster_autodetect import with_default_cluster

    design = with_default_cluster(fixture())
    assert len(design.cluster_transforms) == 1
    relaxed, report = relax_origami(design, max_steps=100)
    assert len(relaxed.cluster_transforms) == 2
    assert all(not c.is_default for c in relaxed.cluster_transforms)
    assert report["rigid_bundle_sizes"] == [1, 1]


def test_clash_prevention_separates_overlapping_bodies_without_splitting_them():
    from backend.core.models import ClusterRigidTransform
    from tools.design_archive.relax_d003_clashes import audit

    design = fixture().copy_with(
        cluster_transforms=[
            ClusterRigidTransform(helix_ids=["a"]),
            ClusterRigidTransform(helix_ids=["b"], translation=[0, -19.5, 0]),
        ]
    )
    assert audit(design)[0]["interbody_helix_pairs_below_2nm"] == 1
    relaxed, report = relax_origami(design, max_steps=300)
    assert len(relaxed.cluster_transforms) == 2
    assert audit(relaxed)[0]["interbody_helix_pairs_below_2nm"] == 0
    assert report["clashes"]["after"]["overlapping_body_pairs"] == 0
    assert report["clashes"]["after"]["minimum_axis_envelope_gap_nm"] >= 2.05 - 1e-6
    second, repeated = relax_origami(relaxed, max_steps=100)
    assert (
        repeated["after"]["rms_bond_error_nm"]
        <= report["after"]["rms_bond_error_nm"] + 1e-6
    )
    assert audit(second)[0]["interbody_helix_pairs_below_2nm"] == 0
