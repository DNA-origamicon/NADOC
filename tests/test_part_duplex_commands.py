"""Duplex input contracts preserve native topology and publish atomically."""

from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import routes_duplex, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_duplex_commands import (
    ConnectDuplexBody, CreateDuplexBody, DuplexReferenceError, PatchDuplexBody,
    build, prepare_command,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.feature_identity import identity_factory
from backend.core.models import (
    Crossover, Design, Direction, Domain, Duplex, HalfCrossover,
    Helix, OverhangBinding, OverhangSpec, Strand, StrandType, SubDomain, Vec3,
)

SEED = "212cb729-37fa-49e4-bb35-c6a0cbd2cd2e"


def source(*, rooted=False, equal=False, binding=False):
    helices, strands, overhangs, crossovers = [], [], [], []
    for index, (key, length, sequence) in enumerate((("a", 8, "A"), ("b", 8 if equal else 4, "T"))):
        def helix(identity, x, count):
            return Helix(id=identity, axis_start=Vec3(x=x, y=0, z=0),
                axis_end=Vec3(x=x, y=0, z=count * BDNA_RISE_PER_BP),
                length_bp=count, phase_offset=0, grid_pos=(index * 2, 0))
        helices.append(helix(key, index * 8, length))
        domains = []
        if rooted:
            root = "root-" + key
            helices.append(helix(root, index * 8 + 2.5, 4))
            domains.append(Domain(helix_id=root, start_bp=3, end_bp=0, direction=Direction.REVERSE))
            crossovers.append(Crossover(id="xo-" + key,
                half_a=HalfCrossover(helix_id=root, index=0, strand=Direction.REVERSE),
                half_b=HalfCrossover(helix_id=key, index=0, strand=Direction.FORWARD)))
        domains.append(Domain(helix_id=key, start_bp=0, end_bp=length - 1,
                              direction=Direction.FORWARD, overhang_id="oh-" + key))
        strands.append(Strand(id="st-" + key, strand_type=StrandType.STAPLE, domains=domains))
        overhangs.append(OverhangSpec(id="oh-" + key, strand_id="st-" + key, helix_id=key,
            sequence=sequence * length,
            sub_domains=[SubDomain(id="sd-" + key, start_bp_offset=0, length_bp=length)]))
    bindings = [OverhangBinding(id="binding", name="B1", created_at=1.0,
        sub_domain_a_id="sd-a", sub_domain_b_id="sd-b", overhang_a_id="oh-a", overhang_b_id="oh-b")] if binding else []
    return Design(helices=helices, strands=strands, overhangs=overhangs,
                  crossovers=crossovers, overhang_bindings=bindings)


def params(**values):
    return {"_proof_version": 1, "history_seed": SEED, "duplex_id": "duplex", **values}


def create_params(**values):
    return params(created_at=4.0,
        left={"overhang_id": "oh-a", "start_bp": 0, "end_bp": 3},
        right={"overhang_id": "oh-b", "start_bp": 0, "end_bp": 3}, **values)


def connect_params(**values):
    return params(created_at=4.0, overhang_a_id="oh-a", overhang_b_id="oh-b",
                  binding_ids=[], **values)


@pytest.fixture
def document():
    token = set_current_doc("native-duplex-contract")
    try:
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def test_graph_lifecycle_preserves_explicit_identity_and_sparse_patch_semantics():
    original = source()
    before = original.model_dump(mode="json")
    created = build("duplex-create", original, create_params())
    edge = created.duplexes[0]
    assert (edge.id, edge.name, edge.created_at, edge.bound) == ("duplex", "D1", 4.0, False)
    assert len(created.cluster_transforms) == 1
    assert created.cluster_transforms[0].is_default
    assert original.model_dump(mode="json") == before
    updated = build("duplex-patch", created, params(name="  My duplex  ", bound=True, left=None))
    assert updated.duplexes[0].name == "My duplex"
    assert updated.duplexes[0].left == edge.left
    assert updated.duplexes[0].bound
    assert updated.strands == original.strands
    removed = build("duplex-delete", updated, params())
    assert not removed.duplexes
    assert removed.strands == original.strands
    assert removed.cluster_transforms == created.cluster_transforms
    assert Design.model_validate_json(updated.model_dump_json()) == updated


@pytest.mark.parametrize("bad", [{"driver": None}, {"bound": None}, {"name": None},
    {"name": " "}, {"bound": "true"}, {"sampled_points": [[0, 0, 0]]}])
def test_public_patch_rejects_invalid_null_coercion_and_geometry_input(bad):
    with pytest.raises(ValidationError):
        PatchDuplexBody.model_validate(bad)


def test_native_inputs_bound_register_work_and_reject_unknown_versions():
    original = source()
    for changes in ({"_proof_version": 2}, {"history_seed": "not-a-uuid"},
                    {"prior_driven_topology": {}},
                    {"left": {"overhang_id": "oh-a", "start_bp": 0, "end_bp": 50000}}):
        with pytest.raises(ValidationError):
            build("duplex-create", original, {**create_params(), **changes})


def test_missing_and_ambiguous_references_are_structured():
    original = source()
    invalid = create_params()
    invalid["left"]["overhang_id"] = "deleted"
    with pytest.raises(DuplexReferenceError) as caught:
        build("duplex-create", original, invalid)
    assert caught.value.as_issue()["references"] == [{
        "kind": "overhang", "identity": "deleted", "parameter_path": ["left", "overhang_id"],
    }]
    duplicate = original.copy_with(overhangs=[*original.overhangs, original.overhangs[0]])
    with pytest.raises(DuplexReferenceError, match="ambiguous"):
        build("duplex-create", duplicate, create_params())


@pytest.mark.parametrize("rooted", [False, True])
def test_connect_matches_unchanged_native_topology_with_live_register_and_stable_ids(rooted):
    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.duplex import connect_register, longest_driver, relocate_duplex

    original = source(rooted=rooted)
    before = original.model_dump(mode="json")
    arguments = connect_params()
    actual = build("duplex-connect", original, arguments)
    left, right = connect_register(original, "oh-a", "free_end", "oh-b", "root")
    edge = Duplex(id="duplex", name="D1", created_at=4.0, left=left, right=right,
                  driver=longest_driver(original, left, right))
    expected = relocate_duplex(original.copy_with(duplexes=[edge]), edge, identity_seed=SEED)
    # Register correction must not alter any placed topology/pose/snapshot.
    for field in ("helices", "strands", "overhangs", "crossovers", "forced_ligations"):
        assert getattr(actual, field) == getattr(expected, field)
    live_left, live_right = connect_register(expected, "oh-a", "free_end", "oh-b", "root")
    expected = expected.copy_with(duplexes=[expected.duplexes[0].model_copy(update={
        "left": live_left, "right": live_right})])
    expected = with_default_cluster(expected, identity_factory=identity_factory(SEED))
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert (actual.duplexes[0].right.start_bp, actual.duplexes[0].right.end_bp) == (7, 4)
    assert Design.model_validate_json(actual.model_dump_json()) == actual
    repeated = build("duplex-connect", original.copy_with(id="other-document"), arguments)
    assert repeated.duplexes == actual.duplexes
    assert repeated.cluster_transforms == actual.cluster_transforms
    assert repeated.forced_ligations == actual.forced_ligations
    if rooted:
        assert [item.id for item in actual.forced_ligations] == [identity_factory(SEED)("duplex-ligation", ["duplex"])]
        assert any(item.overhang_duplex_driver_id == "oh-a" for item in actual.cluster_transforms)
    assert original.model_dump(mode="json") == before


def test_connect_existing_unbound_binding_keeps_graph_only_legacy_semantics():
    original = source(equal=True, binding=True).copy_with(helices=[])
    arguments = prepare_command("duplex-connect", original, connect_params())
    assert arguments["binding_ids"] == ["binding"]
    updated = build("duplex-connect", original, arguments)
    assert updated.strands == original.strands
    assert not updated.duplexes[0].bound
    assert updated.duplexes[0].prior_driven_topology is None
    with pytest.raises(DuplexReferenceError) as caught:
        build("duplex-connect", original.copy_with(overhang_bindings=[]), arguments)
    assert caught.value.as_issue()["references"][0] == {
        "kind": "overhang_binding", "identity": "binding", "parameter_path": ["binding_ids", 0],
    }


def test_connect_missing_geometry_fails_instead_of_publishing_unbound_fallback(document):
    original = source().copy_with(helices=[])
    state.load_design(original)
    before, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    with pytest.raises(HTTPException) as caught:
        routes_duplex.connect_duplex(ConnectDuplexBody(overhang_a_id="oh-a", overhang_b_id="oh-b"))
    assert caught.value.status_code == 404
    assert caught.value.detail["references"][0]["kind"] == "helix"
    assert state.get_design_with_revision() == (before, revision)
    assert state.undo_depth() == depth


def test_connect_exception_restores_revision_undo_redo_and_feature_state(document, monkeypatch):
    from backend.core import duplex
    state.load_design(source())
    routes_duplex.create_duplex(CreateDuplexBody.model_validate({
        "left": {"overhang_id": "oh-a", "start_bp": 0, "end_bp": 3},
        "right": {"overhang_id": "oh-b", "start_bp": 0, "end_bp": 3},
    }))
    state.undo()
    before, revision = state.get_design_with_revision()
    raw = deepcopy(before.model_dump(mode="json"))
    depth = state.undo_depth()

    def fail(*_args, **_kwargs):
        raise ValueError("injected relocation failure")

    monkeypatch.setattr(duplex, "relocate_duplex", fail)
    with pytest.raises(HTTPException, match="injected relocation failure"):
        routes_duplex.connect_duplex(ConnectDuplexBody(overhang_a_id="oh-a", overhang_b_id="oh-b"))
    current, current_revision = state.get_design_with_revision()
    assert current.model_dump(mode="json") == raw
    assert current_revision == revision
    assert state.undo_depth() == depth
    assert state.redo() is not None
    assert len(state.get_or_404().duplexes) == 1


def test_registered_graph_lifecycle_replays_without_saved_outputs(document):
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_history_proof import import_root

    original = source()
    original.recipe_root = import_root(original)
    state.load_design(original)
    routes_duplex.create_duplex(CreateDuplexBody.model_validate({
        "left": {"overhang_id": "oh-a", "start_bp": 0, "end_bp": 3},
        "right": {"overhang_id": "oh-b", "start_bp": 0, "end_bp": 3},
    }))
    identity = state.get_or_404().duplexes[0].id
    routes_duplex.patch_duplex(identity, PatchDuplexBody(name="Authored", driver="right"))
    routes_duplex.delete_duplex(identity)
    current = Design.model_validate_json(state.get_or_404().model_dump_json())
    assert [entry.op_kind for entry in current.feature_log] == ["duplex-create", "duplex-patch", "duplex-delete"]
    for entry in current.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "invalid saved output"
    report = assess_part_history(current, execute=execute, dependencies=dependencies)
    assert report["status"] == "reproduced_import", report
    assert report["checked_commands"] == 3
    state.undo()
    assert state.get_or_404().duplexes[0].name == "Authored"


def test_registered_relocation_replays_from_inputs_after_poisoned_outputs(document):
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_history_proof import import_root

    original = source(rooted=True)
    original.recipe_root = import_root(original)
    state.load_design(original)
    routes_duplex.connect_duplex(ConnectDuplexBody(overhang_a_id="oh-a", overhang_b_id="oh-b"))
    current = Design.model_validate_json(state.get_or_404().model_dump_json())
    assert current.forced_ligations
    assert current.duplexes[0].prior_driven_topology
    entry = current.feature_log[0]
    assert entry.params["binding_ids"] == []
    entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "invalid saved output"
    report = assess_part_history(current, execute=execute, dependencies=dependencies)
    assert report["status"] == "reproduced_import", report
    assert report["checked_commands"] == 1


def test_patch_revalidates_combined_end_lengths_and_binding_selection():
    original = build("duplex-create", source(equal=True, binding=True), create_params())
    with pytest.raises(ValidationError, match="equal length"):
        build("duplex-patch", original, params(left={"overhang_id": "oh-a", "start_bp": 0, "end_bp": 2}))
    with pytest.raises(ValidationError, match="selected binding"):
        build("duplex-patch", original, params(driver="right"))
    selected = prepare_command("duplex-patch", original, params(driver="right"))
    changed = build("duplex-patch", original, selected)
    binding = changed.overhang_bindings[0]
    assert (binding.driver_oh_id, binding.driven_oh_id) == ("oh-b", "oh-a")
    assert changed.strands == original.strands


def test_delete_removes_edge_only_and_preserves_existing_relocation():
    connected = build("duplex-connect", source(), connect_params())
    removed = build("duplex-delete", connected, params())
    assert not removed.duplexes
    for field in ("helices", "strands", "overhangs", "crossovers", "forced_ligations", "cluster_transforms"):
        assert getattr(removed, field) == getattr(connected, field)


def bound_source():
    from backend.core.binding_relax import apply_bind_topology, compute_bind_topology

    original = source(rooted=True, equal=True, binding=True)
    binding = original.overhang_bindings[0]
    topology = compute_bind_topology(original, binding, driver_side="a",
                                     forced_ligation_id="prior-ligation")
    bound = apply_bind_topology(original, topology)
    binding = binding.model_copy(update={"bound": True, "driver_oh_id": "oh-a",
        "driven_oh_id": "oh-b", "prior_driven_topology": topology.snapshot})
    bound = bound.copy_with(overhang_bindings=[binding])
    edges = [Duplex(id=identity, created_at=1.0, name=identity, bound=True,
        left={"overhang_id": "oh-a", "start_bp": a, "end_bp": b},
        right={"overhang_id": "oh-b", "start_bp": 7 - a, "end_bp": 7 - b})
        for identity, a, b in (("duplex", 1, 2), ("other", 4, 5))]
    return bound.copy_with(duplexes=edges)


def test_bound_driver_patch_keeps_native_topology_and_tracks_partial_registers():
    from backend.core.binding_relax import apply_bind_topology, compute_bind_topology, revert_bind_topology
    from backend.core.duplex import bp_to_offset

    original = bound_source()
    before = original.model_dump(mode="json")
    arguments = prepare_command("duplex-patch", original, params(driver="right"))
    actual = build("duplex-patch", original, arguments)
    binding = original.overhang_bindings[0].model_copy(update={
        "driver_oh_id": "oh-b", "driven_oh_id": "oh-a"})
    reverted = revert_bind_topology(original.copy_with(overhang_bindings=[binding]),
                                    binding.prior_driven_topology)
    topology = compute_bind_topology(reverted, binding, driver_side="b",
        forced_ligation_id=identity_factory(SEED)("binding-driver-ligation", [binding.id]))
    expected = apply_bind_topology(reverted, topology)
    expected = expected.copy_with(overhang_bindings=[binding.model_copy(update={
        "prior_driven_topology": topology.snapshot})])
    for field in ("helices", "strands", "overhangs", "crossovers", "forced_ligations", "overhang_bindings"):
        assert getattr(actual, field) == getattr(expected, field)
    assert actual.duplexes[0].driver == "right"
    assert actual.duplexes[1].driver == original.duplexes[1].driver
    for previous, current in zip(original.duplexes, actual.duplexes):
        for side in ("left", "right"):
            old_end, new_end = getattr(previous, side), getattr(current, side)
            old_domain = next(d for s in original.strands for d in s.domains if d.overhang_id == old_end.overhang_id)
            new_domain = next(d for s in actual.strands for d in s.domains if d.overhang_id == new_end.overhang_id)
            assert [bp_to_offset(old_domain, bp) for bp in (old_end.start_bp, old_end.end_bp)] == [
                bp_to_offset(new_domain, bp) for bp in (new_end.start_bp, new_end.end_bp)]
    assert (actual.duplexes[0].left.start_bp, actual.duplexes[0].left.end_bp) == (6, 5)
    assert (actual.duplexes[0].right.start_bp, actual.duplexes[0].right.end_bp) == (1, 2)
    assert Design.model_validate_json(actual.model_dump_json()) == actual
    repeated = build("duplex-patch", original.copy_with(id="different-source"), arguments)
    assert repeated.duplexes == actual.duplexes
    assert repeated.forced_ligations == actual.forced_ligations
    assert original.model_dump(mode="json") == before


@pytest.mark.parametrize("change", ["owner", "length", "ambiguous", "offset"])
def test_register_tracking_rejects_unprovable_correspondence(change):
    from backend.api.part_duplex_commands import _track_registers

    original = bound_source()
    after = original.model_copy(deep=True)
    target = next(s for s in after.strands if s.id == "st-a")
    domain = target.domains[-1]
    domain.start_bp, domain.end_bp = domain.end_bp, domain.start_bp
    domain.direction = Direction.REVERSE
    if change == "owner":
        target.domains.reverse()
    elif change == "length":
        domain.start_bp += 1
    elif change == "ambiguous":
        target.domains.append(domain.model_copy())
    else:
        original.duplexes[0].left.start_bp = -1
        after.duplexes[0].left.start_bp = -1
    with pytest.raises(DuplexReferenceError):
        _track_registers(original, after, {"oh-a"})


def test_driver_reapply_failure_does_not_publish_metadata_only_fallback(document, monkeypatch):
    from backend.core import binding_relax

    state.load_design(bound_source())
    before, revision = state.get_design_with_revision()
    raw = before.model_dump(mode="json")
    depth = state.undo_depth()

    def fail(*_args, **_kwargs):
        raise ValueError("injected bound driver failure")

    monkeypatch.setattr(binding_relax, "compute_bind_topology", fail)
    with pytest.raises(HTTPException, match="injected bound driver failure"):
        routes_duplex.patch_duplex("duplex", PatchDuplexBody(driver="right"))
    current, current_revision = state.get_design_with_revision()
    assert current.model_dump(mode="json") == raw
    assert current_revision == revision
    assert state.undo_depth() == depth
