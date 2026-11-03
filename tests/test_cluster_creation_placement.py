"""Make Cluster preserves prior native placement, including during replay/seek."""

import pytest

from backend.api import crud, routes_clusters as routes, state
from backend.core.models import Design
from backend.core.deformation import deformed_helix_axes
from tests.test_geometry_group_history import _verified
from tests.test_geometry_group_history import document as document


@pytest.mark.parametrize("scope", ["helix", "all", "domain"])
@pytest.mark.parametrize("posed", [False, True])
def test_make_cluster_keeps_native_geometry_and_persistent_owners(document, scope, posed):
    owner = document.cluster_transforms[0]
    if posed:
        routes.update_cluster(owner.id, routes.PatchClusterBody(
            translation=[2, 3, 4], rotation=[0, 0, .3826834323650898, .9238795325112867],
            pivot=[1, 2, 3], commit=True))
    before = state.get_or_404()
    geometry = crud._geometry_for_design(before)
    helices = [h.id for h in before.helices]
    domains = []
    if scope != "all":
        helices = helices[:1]
    if scope == "domain":
        strand = next(s for s in before.strands if s.domains[0].helix_id == helices[0])
        domains = [{"strand_id": strand.id, "domain_index": 0}]
    routes.add_cluster(routes.AddClusterBody(name="Selected arm", helix_ids=helices, domain_ids=domains))
    made = state.get_or_404()
    assert made.feature_log[-1].proof_version == 3
    assert crud._geometry_for_design(made) == geometry
    assert deformed_helix_axes(made) == deformed_helix_axes(before)
    expected_owner = next(c for c in before.cluster_transforms if c.id == owner.id)
    if not posed and scope != "domain":
        expected_owner = expected_owner.model_copy(update={
            "helix_ids": [h for h in expected_owner.helix_ids if h not in helices]})
    assert next(c for c in made.cluster_transforms if c.id == owner.id) == expected_owner
    assert len(made.cluster_transforms) == len(before.cluster_transforms) + 1
    _verified(made)
    for optimized in (False, True):
        live = Design.from_json(made.model_dump_json())
        for position, expected in [(len(before.feature_log) - 1, before), (-1, made)] * 2:
            live = crud._seek_feature_log(live, position, optimized=optimized)
            assert live.cluster_transforms == expected.cluster_transforms
            assert crud._geometry_for_design(live) == geometry
        _verified(live)
    undone, _ = state.undo()
    assert undone.cluster_transforms == before.cluster_transforms
    redone, _ = state.redo()
    assert redone.cluster_transforms == made.cluster_transforms
    _verified(redone)


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("scope", ["helix", "all", "domain"])
def test_make_cluster_preserves_deformation_arm_placement(kind, scope):
    from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform, DomainRef
    from tests.test_part_deformation_preview import _append, native_source

    source = native_source(kind)
    helices = [h.id for h in source.helices]
    if scope != "all":
        helices = helices[:1]
    domains = [DomainRef(strand_id=source.strands[0].id, domain_index=0)] if scope == "domain" else []
    cluster = ClusterRigidTransform(name="Selected arm", helix_ids=helices, domain_ids=domains)
    row = ClusterCreateLogEntry(proof_version=3, cluster_id=cluster.id, name=cluster.name,
        helix_ids=helices, domain_ids=domains, cluster_snapshot=cluster)
    if scope != "all":
        from backend.core.part_command_errors import ReferenceResolutionError
        before = source.model_dump_json()
        with pytest.raises(ReferenceResolutionError, match="arm used by") as caught:
            _append(source, row)
        assert caught.value.references[0]["identity"] == source.deformations[0].id
        assert source.model_dump_json() == before
        return
    result = _append(source, row)
    assert crud._geometry_for_design(result) == crud._geometry_for_design(source)
    assert deformed_helix_axes(result) == deformed_helix_axes(source)
    assert result.cluster_transforms[:-1] == source.cluster_transforms
    _verified(result)


def test_new_cluster_move_is_separate_and_preserves_unselected_native_placement(document):
    owner = document.cluster_transforms[0]
    routes.update_cluster(owner.id, routes.PatchClusterBody(translation=[2, 3, 4], commit=True))
    before = state.get_or_404()
    routes.add_cluster(routes.AddClusterBody(name="Arm", helix_ids=[before.helices[0].id]))
    made = state.get_or_404()
    group = made.cluster_transforms[-1]
    routes.update_cluster(group.id, routes.PatchClusterBody(translation=[1, 0, 0], commit=True))
    moved = state.get_or_404()
    assert [r.feature_type for r in moved.feature_log[-2:]] == ["cluster_create", "cluster_op"]
    old_geometry, new_geometry = crud._geometry_for_design(made), crud._geometry_for_design(moved)
    for old, new in zip(old_geometry, new_geometry):
        if old["helix_id"] != group.helix_ids[0]:
            assert old == new
        else:
            assert new["backbone_position"] == pytest.approx(
                [value + delta for value, delta in zip(old["backbone_position"], [1, 0, 0], strict=True)])
    _verified(moved)
    for optimized in (False, True):
        recovered = crud._seek_feature_log(moved, len(made.feature_log) - 1, optimized=optimized)
        assert recovered.cluster_transforms == made.cluster_transforms
        recovered = crud._seek_feature_log(recovered, -1, optimized=optimized)
        assert crud._geometry_for_design(recovered) == new_geometry
        _verified(recovered)


def test_membership_edit_refuses_existing_deformation_arm_atomically(document):
    from fastapi import HTTPException
    from tests.test_part_deformation_preview import native_source
    source = native_source("bend")
    state.load_design(source)
    owner = source.cluster_transforms[0]
    before, revision, depth = source.model_dump_json(), state.revision(), state.undo_depth()
    with pytest.raises(HTTPException) as caught:
        routes.update_cluster(owner.id, routes.PatchClusterBody(helix_ids=[source.helices[0].id]))
    assert caught.value.status_code == 422
    assert caught.value.detail["references"][0]["identity"] == source.deformations[0].id
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == depth


@pytest.mark.parametrize('missing', ['evicted', 'post', 'all'])
def test_seek_rebuilds_creation_but_refuses_a_missing_producer(document, missing):
    from fastapi import HTTPException
    from backend.api import routes_feature_log
    routes.add_cluster(routes.AddClusterBody(name="Arm", helix_ids=[document.helices[0].id]))
    made = state.get_or_404()
    rows = list(made.feature_log)
    if missing == 'all':
        rows = [e for e in rows if e.feature_type not in {'snapshot', 'routing-cluster'}]
    else:
        rows[0] = rows[0].model_copy(update={'evicted': True} if missing == 'evicted' else {'post_state_gz_b64': ''})
    state.load_design(made.copy_with(feature_log=rows))
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    if missing == 'all':
        with pytest.raises(HTTPException) as caught:
            routes_feature_log.seek_features(routes_feature_log.SeekFeaturesBody(position=-1))
        assert caught.value.status_code == 409
        assert state.get_or_404().model_dump_json() == before
        assert state.revision() == revision and state.undo_depth() == depth
    else:
        routes_feature_log.seek_features(routes_feature_log.SeekFeaturesBody(position=-1))
        restored = state.get_or_404()
        assert restored.helices == made.helices
        assert restored.cluster_transforms == made.cluster_transforms
        assert crud._geometry_for_design(restored) == crud._geometry_for_design(made)
        _verified(restored)
        assert state.undo_depth() == depth + 1
        state.undo()
        assert state.get_or_404().model_dump_json() == before
