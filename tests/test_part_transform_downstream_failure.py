"""Causal numeric pose edits invalidate a later native domain reference."""

from math import cos, pi, sin

import pytest

from backend.api import crud, part_transform_preview_worker as worker
from backend.core import models as m
from backend.core.part_history_contract import create_empty_part
from backend.core.part_verification_capture import CaptureLimit
from tests.test_part_deformation_preview import _append, owned_capture
from tests.test_part_transform_constraint_history import _create_owner, _seed
from tests.test_part_transform_preview import FEATURE, snapshot


def causal_transform_recipe(name="Native transform downstream failure"):
    source = snapshot(create_empty_part(name, "HONEYCOMB"), "bundle-create",
        crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=12, ligate_adjacent=False,
            history_seed=_seed(301)).model_dump(mode="json"), "bundle")
    fixed, moving = [h.id for h in source.helices]
    source = _create_owner(source, "fixed-arm", [fixed])
    source = _create_owner(source, "moving-arm", [moving])
    source = _append(source, m.ClusterOpLogEntry(id=FEATURE, cluster_id="moving-arm",
        translation=[0, 0, 0], rotation=[0, 0, 0, 1], pivot=[0, 0, 0], proof_version=1))
    counts = {s.id: len(s.domains) for s in source.strands}
    # The stationary helix defines the live section. Moving the other owner
    # changes whether this extrusion continues its existing strands.
    source = snapshot(source, "extrude-deformed-continuation",
        crud.BundleDeformedContinuationRequest(cells=[[0, 1]], length_bp=4,
            grid_origin=[0, 0, 0], axis_dir=[0, 0, 1], frame_right=[1, 0, 0], frame_up=[0, 1, 0],
            ref_helix_id=fixed, source_bp=12, history_seed=_seed(302)).model_dump(mode="json"), "continuation")
    strand = next(s for s in source.strands if len(s.domains) > counts.get(s.id, 999))
    owner = m.ClusterRigidTransform(id="later-owner", name="Continuation owner",
        domain_ids=[m.DomainRef(strand_id=strand.id, domain_index=len(strand.domains) - 1)])
    source = _append(source, m.ClusterCreateLogEntry(id="later-owner-feature", cluster_id=owner.id,
        name=owner.name, helix_ids=[], domain_ids=owner.domain_ids, cluster_snapshot=owner, proof_version=2))
    return _append(source, m.ClusterOpLogEntry(id="later-motion", cluster_id=owner.id,
        translation=[0, 0, 0], rotation=[0, 0, 0, 1], pivot=[0, 0, 0], proof_version=1))


@pytest.mark.parametrize("patch", [
    {"translation": [9, 0, 0]},
    {"rotation": [0, 0, sin(pi / 8), cos(pi / 8)]},
], ids=["move", "rotate"])
def test_pose_edit_names_the_first_real_downstream_failure_without_a_candidate(patch):
    source = causal_transform_recipe()
    before = source.model_dump_json()
    operation = {"action": "apply", "feature_id": FEATURE, "params": {}}
    original = worker.evaluate_operation(owned_capture(source), operation)
    assert original["status"] == "ready", original
    result = worker.evaluate_operation(owned_capture(source), {**operation, "params": patch})
    assert result["status"] == "failed", result
    assert result["issues"] == [{"code": "evaluation_rejected", "http_status": 409, "detail": {
        "code": "preview_command_failed", "detail": "Missing domain in overlay target",
        "feature_id": "later-owner-feature",
    }}]
    assert "candidate" not in result
    assert source.model_dump_json() == before


@pytest.mark.parametrize("error,code", [
    (NotImplementedError("unsupported native scope"), "preview_command_failed"),
    (CaptureLimit("bounded capture"), "preview_limit"),
])
def test_environment_and_capacity_refusals_do_not_blame_a_feature(error, code, monkeypatch):
    from backend.api import part_deformation_preview as preview
    from backend.core.part_command_errors import CommandContractError

    monkeypatch.setattr(preview, "_before_command", lambda *args: None)
    def execute(*args):
        raise error
    with pytest.raises(CommandContractError) as caught:
        preview._run("cluster-op", create_empty_part("bounded", "HONEYCOMB"), {}, lambda: None, execute)
    assert caught.value.status == "unverified"
    assert caught.value.code == code
