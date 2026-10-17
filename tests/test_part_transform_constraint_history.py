"""Native constraint producers survive compound-pose history reconstruction.

Fixtures are complete empty-root recipes. Placement creation is an authored
typed command; joints, flexible marks, overhangs and links are native producer
rows. No current-model injection or recovery body supplies their context.
"""

from copy import deepcopy
from uuid import UUID

from fastapi import HTTPException
import pytest

from backend.api import crud, part_deformation_preview_sessions as host, state
from backend.core import models as m
from backend.core.connection_tethers import cluster_connection_tethers, cluster_movable_links
from backend.core.duplex_cluster import duplex_cluster_rotation_points, duplex_cluster_tethers
from backend.core.flexible_segments import all_cluster_gates
from backend.core.part_history_contract import create_empty_part
from backend.core.part_overlay_commands import build as overlay
from tests.conftest import valid_overhang_sites
from tests.test_part_deformation_preview import _append, owned_capture
from tests.test_part_deformation_preview_sessions import cancellation, checkpoint, unchanged
from tests.test_part_pending_connection_versions import append, creation
from tests.test_part_connection_application_commands import _params as application_params
from tests.test_part_transform_preview import FEATURE, snapshot
from tests.test_part_transform_preview_sessions import document, opening, update, verified  # noqa: F401


KINDS = ("flexible", "joint", "duplex", "ss-linker", "ds-linker")


def _seed(value):
    return str(UUID(int=9000 + value))


def _create_owner(source, identity, helices, *, parent=None, translation=None):
    owner = m.ClusterRigidTransform(id=identity, name=identity, helix_ids=helices,
        parent_cluster_id=parent, translation=translation or [0, 0, 0])
    return _append(source, m.ClusterCreateLogEntry(id=f"create-{identity}", proof_version=2,
        cluster_id=owner.id, name=owner.name, helix_ids=owner.helix_ids,
        domain_ids=owner.domain_ids, cluster_snapshot=owner))


def _flexible_prefix():
    source = snapshot(create_empty_part("Native constrained movement", "HONEYCOMB"),
        "bundle-create", crud.BundleRequest(cells=[[0, 0], [0, 1], [1, 0]], length_bp=12,
            strand_filter="scaffold", ligate_adjacent=False, history_seed=_seed(1)).model_dump(mode="json"), "bundle")
    helices = [helix.id for helix in source.helices]
    ids = {"primary": "moving-arm", "auxiliary": "linked-arm", "fixed": "fixed-arm"}
    for role, helix in zip(("primary", "auxiliary", "fixed"), helices, strict=True):
        source = _create_owner(source, ids[role], [helix])
    # Explicit pencil-tool connections, not a hand-authored materialized strand.
    for index, next_helix in enumerate(helices[1:]):
        first = next(s for s in source.strands if s.domains[0].helix_id == helices[0])
        second = next(s for s in source.strands if s.domains[0].helix_id == next_helix)
        source = snapshot(source, "forced-ligation-create", {
            "three_prime_strand_id": first.id, "five_prime_strand_id": second.id,
            "_fl_id": f"tether-junction-{index}", "is_periodic_seam": False,
        }, f"connect-arms-{index}")
    strand = next(s for s in source.strands if len(s.domains) == 3)
    marks = []
    for ordinal, domain in enumerate(strand.domains):
        direction = 1 if domain.end_bp >= domain.start_bp else -1
        bps = list(range(domain.start_bp, domain.end_bp + direction, direction))
        selected = (bps[:3] if ordinal else []) + (bps[-3:] if ordinal < 2 else [])
        for bp in selected:
            marks.append({"id": f"flex-{ordinal}-{bp}", "strand_id": strand.id,
                "domain_index": ordinal, "bp_index": bp, "direction": domain.direction.value})
    source = snapshot(source, "flexible-segment-mark", {
        "marks": marks, "batch": True, "replace": False,
    }, "derive-native-tethers")
    return source, ids


def _overhang_prefix():
    source = snapshot(create_empty_part("Native overhang constraints", "HONEYCOMB"),
        "bundle-create", {"cells": [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]],
            "length_bp": 42, "name": "Native overhang constraints", "lattice_type": "HONEYCOMB",
            "history_seed": _seed(2)}, "bundle")
    sites = valid_overhang_sites(source)
    first = next(site for site in sites if not site["is_five_prime"])
    second = next(site for site in sites if site["is_five_prime"] and site["helix_id"] != first["helix_id"])
    ids = {"primary": "moving-arm", "fixed": "fixed-arm"}
    source = _create_owner(source, ids["fixed"], [first["helix_id"]], translation=[2, -1, .5])
    source = _create_owner(source, ids["primary"], [second["helix_id"]])
    # Resolve each offered native endpoint on the current prefix. The initial
    # site carries only its original source-helix choice across the first edit.
    for index, planned in enumerate((first, second)):
        site = next(site for site in valid_overhang_sites(source)
                    if site["helix_id"] == planned["helix_id"] and site["is_five_prime"] == planned["is_five_prime"])
        before = {item.id for item in source.overhangs}
        source = snapshot(source, "overhang-extrude", {**site, "direction": site["direction"].value,
            "length_bp": 12, "reuse_existing_helix": False, "history_seed": _seed(3 + index)}, f"endpoint-{index}")
        ids["driver" if index == 0 else "driven"] = next(item.id for item in source.overhangs if item.id not in before)
    return source, ids


def _definition(source, ids, kind):
    owners = {owner.id: owner for owner in source.cluster_transforms}
    affected = [ids["primary"], *([ids["auxiliary"]] if ids.get("auxiliary") else [])]
    poses = [{"cluster_id": owner.id, "translation": list(owner.translation), "rotation": list(owner.rotation),
              "pivot": list(owner.pivot), "parent_cluster_id": owner.parent_cluster_id,
              "overhang_duplex_driver_id": owner.overhang_duplex_driver_id}
             for owner in source.cluster_transforms if owner.id in affected]
    assert ids["primary"] in owners and ids["fixed"] in owners
    return {"_proof_version": 1, "primary_cluster_id": ids["primary"],
        "selected_cluster_ids": [ids["primary"]], "poses": poses,
        "authoring": {"mode": "joint" if kind == "joint" else "tethers",
            "joint_id": ids.get("joint"), "fixed_cluster_ids": [ids["fixed"]],
            "pivot_id": ids["joint"] if kind == "joint" else "ssdna"},
        "primary_authored_fields": {}, "legacy_source": None}


def constraint_recipe(kind="flexible", *, suffix=True, driver=False):
    """Return (native source history, stable role IDs) for backend/JS bridges."""
    if kind not in KINDS:
        raise ValueError(kind)
    if kind in {"flexible", "joint"}:
        source, ids = _flexible_prefix()
        if kind == "joint":
            ids["joint"] = "native-hinge"
            source = snapshot(source, "joint-place", {"cluster_id": ids["primary"], "joint_id": ids["joint"],
                "name": "Historical hinge", "local_axis_origin": [1, 2, 3], "local_axis_direction": [0, 1, 0],
                "min_angle_deg": -20, "max_angle_deg": 25}, "joint-create")
            ids["auxiliary_joint"] = "auxiliary-hinge"
            source = snapshot(source, "joint-place", {"cluster_id": ids["auxiliary"], "joint_id": ids["auxiliary_joint"],
                "name": "Other owner hinge", "local_axis_origin": [0, 0, 0], "local_axis_direction": [1, 0, 0],
                "min_angle_deg": -15, "max_angle_deg": 15}, "auxiliary-joint-create")
    else:
        source, ids = _overhang_prefix()
        if kind == "duplex":
            source = snapshot(source, "duplex-connect", {"history_seed": _seed(5), "duplex_id": "native-duplex",
                "created_at": 1.0, "binding_ids": [], "overhang_a_id": ids["driver"],
                "overhang_b_id": ids["driven"], "overhang_a_attach": "free_end", "overhang_b_attach": "root",
                "driver": "left"}, "native-duplex-connect")
            ids["auxiliary"] = next(owner.id for owner in source.cluster_transforms if owner.overhang_duplex_driver_id)
        else:
            connection_type = f"root-to-end-{kind[:2]}dna-linker"
            params = creation(source, connection_type=connection_type,
                overhang_a_seq="ACGTACGTACGTAC", overhang_b_seq="TGCA", bridge_seq="GGNN")
            source = append(source, "connection-version-create", params, "pending-linker")
            source = append(source, "overhang-bulk", application_params(source), "native-linker-apply")
    if driver:
        if kind != "duplex":
            raise ValueError("Only native duplex fixtures have a driver placement")
        ids["counterpart"] = ids["primary"]
        ids["primary"] = ids.pop("auxiliary")
    definition = _definition(source, ids, kind)
    if driver:
        definition["authoring"].update(pivot_id="dup:taut", fixed_cluster_ids=[ids["fixed"], ids["counterpart"]])
    source = snapshot(source, "placement-poses", definition, FEATURE)
    if suffix:
        source = _append(source, m.ClusterOpLogEntry(id="suffix-fixed-pose", cluster_id=ids["fixed"],
            proof_version=1, translation=[-4, 1, 2], rotation=[0, 0, 0, 1], pivot=[0, 0, 0]))
        if kind == "joint":
            source = snapshot(source, "joint-update", {"joint_id": ids["joint"], "max_angle_deg": 75}, "suffix-joint")
    return source, ids


def _owner(design, identity):
    return next(owner for owner in design.cluster_transforms if owner.id == identity)


def _patch(opened):
    poses = deepcopy(opened["control_context"]["inputs"]["poses"])
    for index, pose in enumerate(poses):
        pose["translation"] = [pose["translation"][0] + index + 1, *pose["translation"][1:]]
    return {"poses": poses}


@pytest.mark.parametrize("kind", KINDS)
def test_constraint_fixture_uses_real_producers_and_is_independently_cold_reproducible(kind):
    source, ids = constraint_recipe(kind, suffix=False)
    verified(source)
    assert source.recipe_root.kind == "empty"
    if kind in {"flexible", "joint"}:
        assert len(source.flexible_connections) == 2
        assert {frozenset((c.cluster_a_id, c.cluster_b_id)) for c in source.flexible_connections} == {
            frozenset((ids["primary"], ids["auxiliary"])), frozenset((ids["auxiliary"], ids["fixed"]))}
        assert all_cluster_gates(source)[ids["primary"]]["gate"]
    elif kind == "duplex":
        child = _owner(source, ids["auxiliary"])
        assert child.parent_cluster_id == ids["fixed"] and child.overhang_duplex_driver_id == ids["driver"]
        assert _owner(source, ids["fixed"]).translation == [2, -1, .5]
        links = cluster_movable_links(source, _owner(source, ids["primary"]))
        assert len(links) == 1 and links[0]["link_cluster_id"] == child.id
        assert {t["part_dragged"] for t in links[0]["tethers"]} == {False, True}
        assert len(duplex_cluster_tethers(source, child)) == 2
        assert len(duplex_cluster_rotation_points(source, child)) == 3
    else:
        tethers = cluster_connection_tethers(source, _owner(source, ids["primary"]))
        assert len(tethers) == 1 and tethers[0]["rigid"] is (kind == "ds-linker")
        assert source.connection_versions[0].applied and len(source.overhang_connections) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_actual_constraint_history_prepare_apply_suffix_reload_cold_proof_and_undo(document, kind):  # noqa: F811
    from backend.api import part_transform_preview as preview

    source, ids = constraint_recipe(kind)
    state.load_design(source)
    before = checkpoint()
    prepared = preview.prepare_from_capture(owned_capture(source), FEATURE)
    prefix = prepared.copy_prefix()
    opened = host.prepare(opening(), family="transform")
    assert opened["command_kind"] == opened["evaluated_command_kind"] == "placement-poses"
    assert opened["control_context"]["inputs"]["authoring"]["fixed_cluster_ids"] == [ids["fixed"]]
    assert _owner(prefix, ids["fixed"]).translation != _owner(source, ids["fixed"]).translation
    if kind == "joint":
        assert opened["control_state"]["cluster_joints"][0]["max_angle_deg"] == 25
    if kind == "duplex":
        assert opened["control_state"]["frame_provenance"]["placement_poses"][ids["auxiliary"]] == {
            "parent_cluster_id": ids["fixed"], "frame": "parent-rest"}
    patch = _patch(opened)
    local = preview.evaluate(prepared, patch)
    expected = prefix
    for pose in patch["poses"]:
        expected = overlay("cluster_op", expected, {"_proof_version": 1,
            **{key: pose[key] for key in ("cluster_id", "translation", "rotation", "pivot")}})
    assert local.design.model_dump(mode="json") == expected.model_dump(mode="json")
    assert _owner(local.design, ids["fixed"]) == _owner(prefix, ids["fixed"])
    evaluated = host.evaluate({**update(opened, params=patch), "include_geometry": False}, family="transform")
    assert evaluated["candidate"] is None
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2, params=patch), family="transform")
    candidate = state.get_or_404()
    assert receipt["revision"] == before["revision"] + 1
    assert state.undo_depth() == len(before["history"]) + 1
    assert [row.id for row in candidate.feature_log] == [row.id for row in source.feature_log]
    assert _owner(candidate, ids["fixed"]) == _owner(source, ids["fixed"])
    if kind == "joint":
        assert candidate.cluster_joints[0].max_angle_deg == 75
    loaded = m.Design.from_json(candidate.to_json())
    assert loaded.model_dump(mode="json") == candidate.model_dump(mode="json")
    verified(loaded)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


@pytest.mark.parametrize("failure", ["missing-fixed", "wrong-joint-owner", "changed-driver-frame"])
def test_native_constraint_references_refuse_without_losing_usable_preview(document, failure):  # noqa: F811
    kind = "duplex" if failure == "changed-driver-frame" else "joint"
    source, ids = constraint_recipe(kind)
    state.load_design(source)
    opened = host.prepare(opening(), family="transform")
    before = checkpoint()
    if failure == "missing-fixed":
        patch = {"authoring": {**opened["control_context"]["inputs"]["authoring"], "fixed_cluster_ids": ["absent-fixed"]}}
        path = ["authoring", "fixed_cluster_ids", 0]
    elif failure == "wrong-joint-owner":
        patch = _patch(opened)
        patch.update(authoring={**opened["control_context"]["inputs"]["authoring"],
            "joint_id": ids["auxiliary_joint"], "pivot_id": ids["auxiliary_joint"]})
        path = ["authoring", "joint_id"]
    else:
        patch = _patch(opened)
        index = next(i for i, pose in enumerate(patch["poses"]) if pose["cluster_id"] == ids["auxiliary"])
        patch["poses"][index]["overhang_duplex_driver_id"] = ids["driven"]
        path = ["poses", index, "overhang_duplex_driver_id"]
    with pytest.raises(HTTPException) as caught:
        host.apply(update(opened, params=patch), family="transform")
    assert caught.value.status_code == 422
    assert any(ref["parameter_path"] == path for ref in caught.value.detail["references"])
    unchanged(before)
    assert host.status(cancellation(opened), family="transform")["status"] == "ready"
    assert host.evaluate(update(opened, sequence=2), family="transform")["candidate"] is not None


def test_denied_final_publication_keeps_native_constraint_source_and_history(document, monkeypatch):  # noqa: F811
    source, _ids = constraint_recipe("flexible")
    state.load_design(source)
    opened = host.prepare(opening(), family="transform")
    before = checkpoint()
    def deny(*_args, **_kwargs):
        raise HTTPException(409, detail={"code": "publication_denied", "message": "Injected final refusal"})
    with monkeypatch.context() as patch:
        patch.setattr(host, "publish_replacement", deny)
        with pytest.raises(HTTPException) as caught:
            host.apply(update(opened, params=_patch(opened)), family="transform")
    assert caught.value.detail["code"] == "publication_denied"
    unchanged(before)
    assert host.status(cancellation(opened), family="transform")["status"] == "ready"
    assert host.evaluate(update(opened, sequence=2), family="transform")["candidate"] is not None


@pytest.mark.parametrize("pivot", ["root", "taut"])
def test_direct_native_duplex_child_pivot_history_keeps_parent_and_driver_frame(document, pivot):  # noqa: F811
    from backend.api import part_transform_preview as preview
    from backend.core.duplex_cluster import set_duplex_cluster_pivot

    source, ids = constraint_recipe("duplex", driver=True)
    verified(source)
    state.load_design(source)
    before = checkpoint()
    prepared = preview.prepare_from_capture(owned_capture(source), FEATURE)
    prefix = prepared.copy_prefix()
    opened = host.prepare(opening(), family="transform")
    inputs = opened["control_context"]["inputs"]
    controls = next(item for item in opened["control_state"]["placement_constraints"] if item["cluster_id"] == ids["primary"])
    assert len(controls["rotation_points"]) == 3 and len(controls["tethers"]) == 2
    patch = _patch(opened)
    if pivot == "root":
        point = next(item for item in controls["rotation_points"] if item["overhang_id"] == ids["driver"])
        rebased = _owner(set_duplex_cluster_pivot(prefix, ids["primary"], point["point"]), ids["primary"])
        patch["poses"][0].update(translation=rebased.translation, rotation=rebased.rotation, pivot=rebased.pivot)
        patch["authoring"] = {**inputs["authoring"], "mode": "free", "pivot_id": f"dup:root:{ids['driver']}"}
    local = preview.evaluate(prepared, patch)
    child = _owner(local.design, ids["primary"])
    assert child.parent_cluster_id == ids["fixed"] and child.overhang_duplex_driver_id == ids["driver"]
    for fixed in inputs["authoring"]["fixed_cluster_ids"]:
        assert _owner(local.design, fixed) == _owner(prefix, fixed)
    unchanged(before)
    assert host.apply(update(opened, params=patch), family="transform")["status"] == "applied"
    verified(m.Design.from_json(state.get_or_404().to_json()))
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
