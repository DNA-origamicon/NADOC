"""A/B reconstruction at every cursor, plus dependency and lifecycle boundaries."""
import random
from pathlib import Path

import pytest

from backend.api import crud
from backend.api.state import encode_design_snapshot
from backend.core.design_diff import apply_child_diff_forward, apply_child_diff_run, encode_child_diff
from backend.core.feature_evaluation import (
    Effects, analyze_overwrites, evaluation_plan, evaluate_child_prefix, feature_effects,
)
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    BendParams, ClusterOpLogEntry, ClusterRigidTransform, DeformationLogEntry,
    DeformationOp, Design, MinorMutationLogEntry, OverhangRotationLogEntry,
    OverhangSpec, RoutingClusterLogEntry, SnapshotLogEntry, SubDomain,
)
from scripts import feature_evaluation_reference as reference_evaluator


def child_diff(pre, post):
    a, r, m, size = encode_child_diff(pre, post)
    return MinorMutationLogEntry(op_subtype="strands-color-bulk", label="recorded",
                                diff_added_b64=a, diff_removed_b64=r,
                                diff_modified_b64=m, diff_size_bytes=size)


def recorded_design(anchor, children, final):
    pre, _ = encode_design_snapshot(anchor)
    post, _ = encode_design_snapshot(final)
    return final.copy_with(feature_log=[RoutingClusterLogEntry(
        children=children, pre_state_gz_b64=pre, post_state_gz_b64=post,
    )])


def pose(cid, x):
    return ClusterOpLogEntry(cluster_id=cid, translation=[x, 0, 0],
                             rotation=[0, 0, 0, 1], pivot=[x / 2, 0, 0])


def assert_ab(design, position, sub_position=None):
    before = design.model_dump()
    a = reference_evaluator._seek_feature_log(design, position, sub_position)
    b = crud._seek_feature_log(design, position, sub_position, optimized=True)
    assert a.model_dump() == b.model_dump()
    assert design.model_dump() == before
    return b


def test_backward_analysis_reads_partial_writes_and_unknown_barriers():
    x, y = ("X",), ("Y",)
    set_x = Effects(writes=frozenset({x}))
    assert analyze_overwrites([set_x, set_x, set_x]) == [True, True, False]
    # A live read of X produces Y: it pins the earlier X assignment.
    read_x = Effects(reads=frozenset({x}), writes=frozenset({y}))
    assert analyze_overwrites([set_x, read_x, set_x]) == [False, False, False]
    assert analyze_overwrites([set_x, Effects(known=False), set_x]) == [False] * 3
    assert analyze_overwrites([Effects(writes=frozenset({x, y})), set_x]) == [False, False]
    # If the reader's entire output is also dead, its input becomes dead too.
    assert analyze_overwrites([set_x, read_x, set_x, Effects(writes=frozenset({y}))]) == [True, True, False, False]


def test_plan_is_target_local_and_updates_after_in_place_edit():
    d = Design(feature_log=[pose("A", 1), pose("B", 2), pose("A", 3)])
    assert [r["action"] for r in evaluation_plan(d, -1)["entries"]] == ["superseded", "execute", "execute"]
    assert evaluation_plan(d, 0)["entries"][0]["action"] == "execute"
    d.feature_log[-1].cluster_id = "C"
    assert evaluation_plan(d, -1)["entries"][0]["action"] == "execute"
    assert evaluation_plan(d, -2)["entries"] == []


def test_mixed_orientation_batch_is_only_partially_overwritten():
    entry = OverhangRotationLogEntry(overhang_ids=["a", "a"], rotations=[[0, 0, 0, 1]] * 2,
        sub_domain_ids=[None, "sd"], sub_domain_thetas_deg=[None, 10], sub_domain_phis_deg=[None, 20])
    later = OverhangRotationLogEntry(overhang_ids=["a"], rotations=[[0, 0, 1, 0]])
    assert analyze_overwrites([feature_effects(entry), feature_effects(later)]) == [False, False]


def test_overlay_ab_every_cursor_and_geometry_after_edit():
    base = make_bundle_design([(0, 0), (0, 1)], length_bp=21)
    ct = ClusterRigidTransform(id="A", helix_ids=[base.helices[0].id])
    ov = OverhangSpec(id="ov", helix_id=base.helices[1].id, strand_id=base.strands[0].id,
                     sub_domains=[SubDomain(id="sd")])
    bend = DeformationOp(type="bend", plane_a_bp=0, plane_b_bp=10,
                        affected_helix_ids=[base.helices[0].id], params=BendParams(curvature_deg_per_bp=0.1))
    log = []
    for i in range(40):
        if i % 3 == 0:
            log.append(pose("A", i))
        elif i % 3 == 1:
            log.append(OverhangRotationLogEntry(overhang_ids=["ov"], rotations=[[0, 0, 0, 1]]))
        else:
            log.append(OverhangRotationLogEntry(overhang_ids=["ov"], rotations=[[0, 0, 0, 1]],
                       sub_domain_ids=["sd"], sub_domain_thetas_deg=[i], sub_domain_phis_deg=[i]))
    log.insert(10, DeformationLogEntry(deformation_id=bend.id, op_snapshot=bend))
    # Legacy deformation lookup must also preserve order and duplicate operations.
    log.insert(20, DeformationLogEntry(deformation_id=bend.id))
    d = base.copy_with(feature_log=log, cluster_transforms=[ct], overhangs=[ov], deformations=[bend])
    for position in [-2, *range(len(log)), -1, 500]:
        assert_ab(d, position)
    d.feature_log[0].translation = [50, 0, 0]
    for position in (0, -1):
        a = crud._seek_feature_log(d, position, optimized=False)
        b = assert_ab(d, position)
        assert crud._compact_geometry_for_design(a) == crud._compact_geometry_for_design(b)


@pytest.mark.parametrize("seed", range(5))
def test_composed_patches_match_every_prefix_with_lifecycle_changes(seed):
    rng = random.Random(seed)
    anchor = make_bundle_design([(0, 0), (0, 1)], length_bp=21)
    original = anchor.model_dump()
    current, children = anchor, []
    for i in range(35):
        strands = list(current.strands)
        action = rng.choice(["modify", "add", "remove"])
        if action == "add" or not strands:
            strands.append(anchor.strands[0].model_copy(update={"id": f"new-{i}"}))
        elif action == "remove":
            strands.pop(rng.randrange(len(strands)))
        else:
            j = rng.randrange(len(strands))
            strands[j] = strands[j].model_copy(update={"color": f"#{i + 1:06x}"})
        post = current.copy_with(strands=strands)
        child = child_diff(current, post)
        children.append(child)
        current, _ = apply_child_diff_forward(current, child.diff_added_b64,
                                              child.diff_removed_b64, child.diff_modified_b64)
        got = apply_child_diff_run(anchor, children)
        assert got.model_dump() == current.model_dump()
        assert anchor.model_dump() == original
    d = recorded_design(anchor, children, current)
    for j in range(len(children)):
        assert_ab(d, 0, j)


def test_remove_readd_and_absent_modify_preserve_reference_order():
    anchor = make_bundle_design([(0, 0), (0, 1)], length_bp=21)
    removed = anchor.copy_with(strands=anchor.strands[1:])
    modified = anchor.copy_with(strands=[anchor.strands[0].model_copy(update={"color": "#abcdef"}), *anchor.strands[1:]])
    readded = removed.copy_with(strands=[*removed.strands, modified.strands[0]])
    children = [child_diff(anchor, removed), child_diff(anchor, modified), child_diff(removed, readded)]
    out = apply_child_diff_run(anchor, children)
    assert out.strands == readded.strands
    # Duplicate ids are invalid canonical topology but retain reference list behavior.
    duplicate = readded.copy_with(strands=[*readded.strands, readded.strands[0]])
    a = apply_child_diff_run(duplicate, children)
    b = duplicate
    for c in children:
        b, _ = apply_child_diff_forward(b, c.diff_added_b64, c.diff_removed_b64, c.diff_modified_b64)
    assert a == b


def test_legacy_operation_observes_flushed_prefix_and_is_not_skipped():
    anchor = make_bundle_design([(0, 0)], length_bp=21)
    current, children = anchor, []
    for i in range(10):
        post = current.copy_with(strands=[current.strands[0].model_copy(update={"color": f"#{i + 1:06x}"}), *current.strands[1:]])
        children.append(child_diff(current, post))
        current = post
    legacy = MinorMutationLogEntry(op_subtype="strand-delete", label="legacy", params={})
    seen = []

    def replay(d, subtype, params):
        seen.append(d.strands[0].color)
        return d.copy_with(strands=d.strands[1:])

    out = evaluate_child_prefix(anchor, children + [legacy], replay, optimized=True)
    assert seen == ["#00000a"]
    assert out.strands == current.strands[1:]
    d = recorded_design(anchor, children + [legacy], out)
    plan = evaluation_plan(d, 0, 9)
    assert [c["action"] for c in plan["topology"]["children"]] == ["superseded"] * 9 + ["apply_recorded_state"]
    assert evaluation_plan(d, 0, 3)["topology"]["children"][-1]["action"] == "apply_recorded_state"
    assert evaluation_plan(d, 0, 10)["topology"]["children"][-1]["action"] == "execute"


def test_resize_grow_shrink_and_crossover_use_recorded_topology():
    anchor = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    strand = next(s for s in anchor.strands if s.domains[0].direction.value == "FORWARD")
    current, children = anchor, []
    for delta in [8, -3, 2, -7, 4, -4, 2, -2]:
        request = crud.StrandEndResizeRequest.model_validate({"entries": [{
            "strand_id": strand.id, "helix_id": strand.domains[0].helix_id,
            "end": "3p", "delta_bp": delta,
        }]})
        post = crud._build_strand_end_resize(current.model_copy(deep=True), request)
        children.append(child_diff(current, post))
        current = post
    # The endpoint returned to its original value; the grown axis must survive.
    assert current.helices != anchor.helices
    request = crud.PlaceCrossoverRequest.model_validate({
        "half_a": {"helix_id": anchor.helices[0].id, "index": 7, "strand": "REVERSE"},
        "half_b": {"helix_id": anchor.helices[1].id, "index": 7, "strand": "FORWARD"},
        "nick_bp_a": 7, "nick_bp_b": 6,
    })
    post, _, _ = crud._build_place_crossover(current.model_copy(deep=True), request)
    children.append(child_diff(current, post))
    d = recorded_design(anchor, children, post)
    for j in range(len(children)):
        assert_ab(d, 0, j)
    out = assert_ab(d, 0, len(children) - 1)
    assert out.helices == post.helices
    assert out.crossovers == post.crossovers


def test_snapshot_selection_eviction_and_all_cursor_aliases():
    base = make_bundle_design([(0, 0)], length_bp=21)
    pre, _ = encode_design_snapshot(Design())
    post, _ = encode_design_snapshot(base)
    entry = SnapshotLogEntry(op_kind="bundle-create", label="create", design_snapshot_gz_b64=pre, post_state_gz_b64=post)
    d = base.copy_with(feature_log=[*[pose("A", i) for i in range(35)], entry, pose("A", 36)])
    for position in (-2, 0, 34, 35, 36, -1, 99):
        assert_ab(d, position)
    entry.evicted = True
    for position in (-2, 10, -1):
        assert_ab(d, position)


def test_geometry_batch_only_materializes_requested_distinct_states(monkeypatch):
    from backend.api import routes_feature_log as routes
    d = Design(feature_log=[pose("A", i) for i in range(4)],
               cluster_transforms=[ClusterRigidTransform(id="A")])
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: d)
    calls = []
    def geometry(state, **kwargs):
        value = state.cluster_transforms[0].translation[0]
        calls.append(value)
        return {"pose": value}
    monkeypatch.setattr(routes, "_compact_geometry_for_design", geometry)
    monkeypatch.setattr(routes, "deformed_helix_axes", lambda d: [])
    body = routes.GeometryBatchBody(positions=[0, 2, 3, -1, 100, 0])
    monkeypatch.setenv("NADOC_FEATURE_EVALUATION", "baseline")
    a = routes.geometry_batch(body)
    assert len(calls) == 5
    calls.clear()
    monkeypatch.setenv("NADOC_FEATURE_EVALUATION", "optimized")
    b = routes.geometry_batch(body)
    assert b == a
    assert calls == [0, 2, 3]
    assert d.feature_log_cursor == -1


def test_plan_endpoint_is_read_only(monkeypatch):
    from backend.api import routes_feature_log as routes
    d = Design(feature_log=[pose("A", i) for i in range(4)])
    before = d.model_dump()
    monkeypatch.setattr(routes.design_state, "get_or_404", lambda: d)
    result = routes.get_evaluation_plan(position=2)
    assert [r["action"] for r in result["entries"]] == ["superseded", "superseded", "execute"]
    assert d.model_dump() == before


@pytest.mark.parametrize("filename", ["corner_miter_test.nadoc", "relax_2x2_closebond.nadoc"])
def test_saved_design_every_top_level_and_child_cursor(filename, monkeypatch):
    d = Design.from_json((Path(__file__).parent / "fixtures" / filename).read_text())
    for position in [-2, *range(len(d.feature_log)), -1]:
        assert_ab(d, position)
    monkeypatch.setenv("NADOC_FEATURE_EVALUATION", "optimized")
    for i, entry in enumerate(d.feature_log):
        if entry.feature_type == "routing-cluster" and not entry.evicted:
            for j in range(len(entry.children)):
                assert_ab(d, i, j)
                a = reference_evaluator._state_at_child_boundary(entry, j + 1)
                b = crud._state_at_child_boundary(entry, j + 1)
                assert a.model_dump() == b.model_dump()
