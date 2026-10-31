"""Retain explicit same-body strain without changing ordinary root constraints."""

from unittest.mock import patch

import pytest

from backend.core.direct_root_placement import capture_root_lengths, place_direct_roots
from backend.core.direct_root_policy import host_root_owner, root_length_exemptions
from backend.core.models import ClusterJoint, ClusterRigidTransform, DomainRef, FlexibleSegmentMark
from tests.test_direct_connection_unified import _seed
from tests.test_direct_root_constraints import unplaced


def test_same_rigid_body_keeps_exact_relocated_pose_and_relax_is_a_noop():
    from backend.core.direct_relax import relax_direct_binding

    source = _seed(same_body=True)
    raw = unplaced(source)
    targets = capture_root_lengths(source, ["oh_a", "oh_b"])
    before = raw.model_dump_json()
    assert capture_root_lengths(raw, targets)["oh_b"]["viewer"] > targets["oh_b"]["viewer"] + 1
    assert place_direct_roots(raw, "oh_a", targets) is raw
    relaxed, info = relax_direct_binding(raw, "oh_a", "oh_b")
    assert relaxed is raw
    assert raw.model_dump_json() == before
    assert info["unchanged"] and info["mode"] == "root_length_exemption"
    assert info["moved_cluster_ids"] == []
    assert "does not infer" in info["message"]


def test_owner_is_host_domain_not_relocated_duplex_or_shared_ancestor():
    source = _seed(same_body=True)
    a = ClusterRigidTransform(id="arm-a", parent_cluster_id="cAB", helix_ids=["d_ha"],
                             domain_ids=[DomainRef(strand_id="d_sa", domain_index=0)])
    b = ClusterRigidTransform(id="arm-b", parent_cluster_id="cAB", helix_ids=["d_hb"],
                             domain_ids=[DomainRef(strand_id="d_sb", domain_index=0)])
    arms = source.copy_with(cluster_transforms=[*source.cluster_transforms, a, b],
                            cluster_joints=[ClusterJoint(cluster_id="arm-b")])
    assert host_root_owner(arms, "oh_a") == "arm-a"
    assert host_root_owner(arms, "oh_b") == "arm-b"
    assert not root_length_exemptions(arms, ["oh_a", "oh_b"])
    assert not root_length_exemptions(source.copy_with(cluster_transforms=[]), ["oh_a", "oh_b"])


def test_common_body_joint_and_unrelated_flex_do_not_invent_relative_motion():
    source = _seed(same_body=True)
    source = source.copy_with(cluster_joints=[ClusterJoint(cluster_id="cAB")],
        flexible_segment_marks=[FlexibleSegmentMark(strand_id="stale", domain_index=0,
                                                   bp_index=0, direction="FORWARD")])
    assert root_length_exemptions(source, ["oh_a", "oh_b"])[0]["cluster_id"] == "cAB"


def test_flexible_host_anchor_is_not_treated_as_fixed_to_a_rigid_body():
    source = _seed(same_body=True)
    source = source.copy_with(flexible_segment_marks=[FlexibleSegmentMark(
        strand_id="d_sa", domain_index=0, bp_index=3, direction="FORWARD")])
    assert host_root_owner(source, "oh_a") is None
    assert not root_length_exemptions(source, ["oh_a", "oh_b"])


def test_extra_nonexempt_root_cannot_borrow_the_exemption(monkeypatch):
    from backend.core import direct_root_placement
    from fastapi import HTTPException

    raw = unplaced(_seed(same_body=True))
    targets = {**capture_root_lengths(raw, ["oh_a", "oh_b"]), "other": {"viewer": .2, "export": .2}}
    monkeypatch.setattr(direct_root_placement, "capture_root_lengths", lambda *_: {
        **targets, "other": {"viewer": 5., "export": 5.}})
    with pytest.raises(HTTPException, match="preserving its covalent root bonds"):
        place_direct_roots(raw, "oh_a", targets)


@pytest.fixture(scope="module")
def native():
    from experiments.direct_linker_native import native_source, connection_inputs
    from tests.test_part_pending_connection_versions import append

    source = native_source()
    return source, append(source, "overhang-bulk", connection_inputs(source), "direct-exempt")


def test_native_connect_matches_unfitted_geometry_and_cold_replays(native):
    from backend.api.part_proof_commands import execute
    from backend.core.atomistic import build_atomistic_model
    from backend.core.direct_root_policy import direct_connection_exemptions
    from experiments.direct_linker_native import connection_inputs
    from tests.test_part_pending_connection_versions import proof

    source, connected = native
    with patch("backend.core.direct_root_placement.place_direct_roots", lambda d, *_: d):
        unfitted = execute("overhang-bulk", source, connection_inputs(source))
    for fast in (True, False):
        assert build_atomistic_model(connected, fast_bridges=fast) == build_atomistic_model(unfitted, fast_bridges=fast)
    result = proof(connected)
    assert result["status"] == "verified", result
    assert result["checked_commands"] == 4
    assert len(direct_connection_exemptions(connected)) == 1  # binding + duplex deduplicated
    driven = connected.overhang_bindings[0].driven_oh_id
    assert capture_root_lengths(connected, [driven])[driven]["viewer"] == pytest.approx(7.558951938676602)


def test_native_unapply_restores_exact_original_atoms_and_replays(native):
    from backend.api.part_connection_disconnect import capture_inputs
    from backend.core.atomistic import build_atomistic_model
    from tests.test_part_pending_connection_versions import append, proof

    source, connected = native
    inputs = capture_inputs(connected, connected.connection_versions[0], delete_version=False)
    restored = append(connected, "overhang-bulk", inputs, "unapply-exempt")
    for fast in (True, False):
        assert build_atomistic_model(restored, fast_bridges=fast) == build_atomistic_model(source, fast_bridges=fast)
    assert proof(restored)["status"] == "verified"


def test_notice_is_nonblocking_and_survives_reload_namespace_and_manual_strain(native):
    from backend.core.duplex_cluster import duplex_cluster_for
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.part_scope_references import namespace_design
    from backend.core.validator import validate_design
    from backend.api.crud import _validation_dict

    _, connected = native
    restored = type(connected).model_validate_json(connected.model_dump_json())
    mapped = namespace_design(restored, "00000000-0000-0000-0000-000000009215")
    child = duplex_cluster_for(mapped, mapped.overhang_bindings[0].driver_oh_id)
    moved = mapped.copy_with(cluster_transforms=[c.model_copy(update={"translation": [20., 30., 40.]})
        if c.id == child.id else c for c in mapped.cluster_transforms])
    binding = moved.overhang_bindings[0]
    assert relax_direct_binding(moved, binding.driver_oh_id, binding.driven_oh_id)[0] is moved
    report = validate_design(moved)
    assert report.passed
    notice = _validation_dict(report, moved)["exemptions"][0]
    assert set(notice["overhang_ids"]) == {o.id for o in mapped.overhangs}
    assert notice["cluster_id"] in {c.id for c in mapped.cluster_transforms}
    assert "Existing strain is retained" in notice["message"]
    from backend.api.part_ordinary_recipe_recording import _validation
    from dataclasses import asdict
    worker_report = _validation({"passed": report.passed, **asdict(report)}, code="test")
    assert _validation_dict(worker_report, moved)["exemptions"] == [notice]


@pytest.mark.parametrize("kind", ["binding", "duplex"])
def test_relax_endpoint_does_not_publish_or_create_undo_for_exemption(native, monkeypatch, kind):
    from backend.api import state, crud, routes_duplex, routes_relaxation

    source, connected = native
    if kind == "duplex":
        from backend.api.part_duplex_commands import build
        from experiments.direct_linker_native import connect_inputs
        connected = build("duplex-connect", source, connect_inputs(source))
    monkeypatch.setattr(state, "get_or_404", lambda: connected)
    def unexpected(*_):
        pytest.fail("Exempt Relax must not publish an unchanged design")
    monkeypatch.setattr(state, "set_design", unexpected)
    response = lambda d, r: {"validation": crud._validation_dict(r, d)}
    monkeypatch.setattr(crud, "_design_response_with_geometry", response)
    monkeypatch.setattr(routes_relaxation, "_design_response_with_geometry", response)
    payload = (routes_relaxation.relax_overhang_binding(connected.overhang_bindings[0].id)
               if kind == "binding" else routes_duplex.relax_duplex(connected.duplexes[0].id))
    assert payload["relax_info"]["unchanged"]
    assert payload["validation"]["exemptions"]
