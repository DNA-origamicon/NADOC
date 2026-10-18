"""Explicit binding selection and legacy compatibility for native duplex sync."""

import pytest
from pydantic import ValidationError

from backend.api import crud, routes_duplex, state
from backend.api.part_duplex_commands import DuplexReferenceError, build, prepare_command
from backend.core.models import Design
from tests.test_part_duplex_commands import SEED, document, source  # noqa: F401 — shared isolated-document fixture


def arguments(design):
    return prepare_command("duplex-sync-bindings", design, {"_proof_version": 1, "history_seed": SEED})


def test_sync_matches_legacy_registers_names_and_compatibility_fields():
    from backend.core.duplex import sync_duplexes_from_bindings

    original = source(equal=True, binding=True)
    binding = original.overhang_bindings[0].model_copy(update={
        "driver_oh_id": "oh-b", "driven_oh_id": "oh-a", "binding_mode": "toehold",
        "connection_type": "root-to-root", "locked_angle_deg": 13.0,
        "created_at": 12.5, "name": "Custom binding label",
    })
    original = original.copy_with(overhang_bindings=[binding])
    params = arguments(original)
    result = build("duplex-sync-bindings", original, params)
    legacy = sync_duplexes_from_bindings(original)
    expected = legacy.duplexes[0].model_copy(update={"id": params["duplex_ids"][0]})
    assert result.duplexes == [expected]
    assert result.duplexes[0].name == "D1"
    assert params["binding_ids"] == ["binding"]
    assert params["created_at"] == [12.5]
    assert not original.duplexes
    assert result.strands == original.strands
    assert result.overhang_bindings == original.overhang_bindings
    again = build("duplex-sync-bindings", original.copy_with(id="another-document"), params)
    assert again.duplexes == result.duplexes
    assert again.cluster_transforms == result.cluster_transforms
    assert Design.model_validate_json(result.model_dump_json()) == result


def test_route_selection_retains_first_pair_order_and_explicit_empty_selection():
    original = source(equal=True, binding=True)
    duplicate_pair = original.overhang_bindings[0].model_copy(update={"id": "second", "created_at": 9.0})
    original = original.copy_with(overhang_bindings=[duplicate_pair, *original.overhang_bindings])
    params = arguments(original)
    assert params["binding_ids"] == ["second"]
    assert params["created_at"] == [9.0]
    updated = build("duplex-sync-bindings", original, params)
    empty = arguments(updated)
    assert empty["binding_ids"] == empty["duplex_ids"] == empty["created_at"] == []
    assert build("duplex-sync-bindings", updated, empty) == updated
    with pytest.raises(DuplexReferenceError, match="already has a duplex"):
        build("duplex-sync-bindings", updated, params)


def test_replay_ignores_unselected_bindings_instead_of_broad_reselection():
    original = source(equal=True, binding=True)
    params = arguments(original)
    extra = original.overhang_bindings[0].model_copy(update={
        "id": "unselected", "overhang_a_id": "unresolved-a", "overhang_b_id": "unresolved-b",
        "sub_domain_a_id": "unresolved-sd-a", "sub_domain_b_id": "unresolved-sd-b",
    })
    expanded = original.copy_with(overhang_bindings=[extra, *original.overhang_bindings])
    result = build("duplex-sync-bindings", expanded, params)
    assert len(result.duplexes) == 1
    assert result.duplexes[0].id == params["duplex_ids"][0]
    assert result.duplexes[0].left.overhang_id == "oh-a"
    # A new authoring request does select the new missing pair, then reports its
    # unresolved dependencies instead of silently dropping it as legacy sync did.
    with pytest.raises(DuplexReferenceError):
        build("duplex-sync-bindings", expanded, arguments(expanded))


@pytest.mark.parametrize("missing", ["binding", "subdomain", "overhang", "domain", "joint"])
def test_selected_missing_dependencies_are_structured(missing):
    original = source(equal=True, binding=True)
    params = arguments(original)
    if missing == "binding":
        original = original.copy_with(overhang_bindings=[])
    elif missing == "subdomain":
        original = original.copy_with(overhangs=[original.overhangs[0].model_copy(update={"sub_domains": []}),
                                                original.overhangs[1]])
    elif missing == "overhang":
        original = original.copy_with(overhang_bindings=[original.overhang_bindings[0].model_copy(update={
            "overhang_a_id": "deleted-overhang"})])
    elif missing == "domain":
        original = original.copy_with(strands=[original.strands[1]])
    else:
        original = original.copy_with(overhang_bindings=[original.overhang_bindings[0].model_copy(update={
            "target_joint_id": "deleted-joint"})])
    with pytest.raises(DuplexReferenceError) as caught:
        build("duplex-sync-bindings", original, params)
    reference = caught.value.as_issue()["references"][0]
    assert reference["parameter_path"] == ["binding_ids", 0]
    assert reference["kind"] in {"overhang_binding", "overhang", "subdomain", "cluster_joint"}


def test_ambiguous_subdomain_and_output_identity_collision_are_rejected():
    original = source(equal=True, binding=True)
    params = arguments(original)
    ambiguous = original.copy_with(overhangs=[original.overhangs[0], original.overhangs[1].model_copy(update={
        "sub_domains": [*original.overhangs[1].sub_domains, original.overhangs[0].sub_domains[0]]})])
    with pytest.raises(DuplexReferenceError, match="ambiguous"):
        build("duplex-sync-bindings", ambiguous, params)
    connected = build("duplex-sync-bindings", original, params)
    collision = connected.duplexes[0].model_copy(update={
        "left": connected.duplexes[0].left.model_copy(update={"overhang_id": "elsewhere"})})
    with pytest.raises(DuplexReferenceError) as caught:
        build("duplex-sync-bindings", original.copy_with(duplexes=[collision]), params)
    assert caught.value.as_issue()["references"][0]["parameter_path"] == ["duplex_ids", 0]


@pytest.mark.parametrize("changes", [
    {"_proof_version": 2}, {"duplex_ids": []}, {"created_at": []},
    {"created_at": [float("inf")]}, {"output_geometry": {}},
    {"binding_ids": ["binding", "binding"], "duplex_ids": ["x", "y"], "created_at": [1.0, 1.0]},
])
def test_sync_contract_rejects_unaligned_or_unbounded_metadata(changes):
    original = source(equal=True, binding=True)
    with pytest.raises(ValidationError):
        build("duplex-sync-bindings", original, {**arguments(original), **changes})


def test_sync_bounds_source_register_before_constructing_edge(monkeypatch):
    from backend.core import duplex

    original = source(equal=True, binding=True)
    overhangs = [item.model_copy(update={"sub_domains": [item.sub_domains[0].model_copy(update={
        "length_bp": 50_001})]}) for item in original.overhangs]
    original = original.copy_with(overhangs=overhangs)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Out-of-budget register reached native construction")

    monkeypatch.setattr(duplex, "synthesize_duplex_from_binding", unexpected)
    with pytest.raises(DuplexReferenceError, match="budget"):
        build("duplex-sync-bindings", original, arguments(original))


def test_sync_preserves_legacy_mismatch_classification_policy():
    from backend.core.duplex import classify_duplex_pairing

    original = source(equal=True, binding=True)
    original = original.copy_with(overhangs=[item.model_copy(update={"sequence": "A" * 8})
                                            for item in original.overhangs])
    result = build("duplex-sync-bindings", original, arguments(original))
    assert classify_duplex_pairing(result, result.duplexes[0])["n_mismatch"] == 8


@pytest.mark.usefixtures("document")
def test_sync_delete_cold_replay_and_reload_preserve_authored_empty_graph():
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_history_proof import import_root

    original = source(equal=True, binding=True)
    original.recipe_root = import_root(original)
    state.load_design(original)
    routes_duplex.sync_from_bindings()
    current = state.get_or_404()
    entry = current.feature_log[-1]
    assert entry.op_kind == "duplex-sync-bindings"
    assert entry.params["binding_ids"] == ["binding"]
    identity = current.duplexes[0].id
    routes_duplex.delete_duplex(identity)
    saved = state.get_or_404().model_dump_json()
    loaded = Design.from_json(saved)
    loaded = crud._derive_duplexes_if_empty(loaded)
    loaded = crud._materialize_duplex_clusters_on_load(loaded)
    assert not loaded.duplexes
    assert loaded.overhang_bindings
    for entry in loaded.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "invalid saved output"
    report = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert report["status"] == "reproduced_import", report
    assert report["checked_commands"] == 2
    state.undo()
    assert state.get_or_404().duplexes[0].id == identity


def test_rootless_legacy_derivation_remains_available():
    original = source(equal=True, binding=True)
    derived = crud._derive_duplexes_if_empty(original)
    assert len(derived.duplexes) == 1
    assert derived.duplexes[0].created_at == original.overhang_bindings[0].created_at
    assert crud._derive_duplexes_if_empty(derived) is derived
