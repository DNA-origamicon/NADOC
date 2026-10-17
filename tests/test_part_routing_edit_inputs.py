"""Closed Fine Routing authoring inputs; native topology remains the executor's job."""

from copy import deepcopy
from uuid import UUID

import pytest

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


X1 = "00000000-0000-4000-8000-000000000001"
X2 = "00000000-0000-4000-8000-000000000002"
X3 = "00000000-0000-4000-8000-000000000003"


def placement(identity=X1):
    return {"crossover_id": identity,
        "half_a": {"helix_id": "h", "index": 4, "strand": "FORWARD"},
        "half_b": {"helix_id": "other", "index": 4, "strand": "REVERSE"},
        "nick_bp_a": 4, "nick_bp_b": 3, "process_id": "manual"}


CASES = {
    "strand-end-resize": {"entries": [{"strand_id": "s", "helix_id": "h", "end": "3p", "delta_bp": -2}]},
    "domain-shift": {"entries": [{"strand_id": "s", "domain_index": 0, "delta_bp": -2}]},
    "nick": {"helix_id": "h", "bp_index": 4, "direction": "FORWARD"},
    "nick-batch": {"nicks": [{"helix_id": "h", "bp_index": 4, "direction": "FORWARD"}]},
    "ligate": {"helix_id": "h", "bp_index": 4, "direction": "REVERSE"},
    "forced-ligation-create": {"_fl_id": "fl-new", "three_prime_strand_id": "s", "five_prime_strand_id": "second", "is_periodic_seam": False},
    "forced-ligation-delete": {"fl_id": "fl"},
    "forced-ligation-delete-batch": {"forced_ligation_ids": ["fl"]},
    "forced-ligation-extra-bases": {"fl_id": "fl", "sequence": "ACGTN"},
    "crossover-place": placement(),
    "crossover-place-batch": {"placements": [placement()]},
    "crossover-move": {"crossover_id": X1, "new_index": 5},
    "crossover-move-batch": {"moves": [{"crossover_id": X1, "new_index": 5}]},
    "crossover-delete": {"crossover_id": X1},
    "crossover-delete-batch": {"crossover_ids": [X1]},
    "crossover-extra-bases": {"crossover_id": X1, "sequence": "ACGTN"},
    "crossover-extra-bases-batch": {"entries": [{"crossover_id": X1, "sequence": "ACGTN"}]},
    "loop-skip-insert": {"helix_id": "h", "bp_index": 3, "delta": -1},
    "loop-skip-twist": {"helix_ids": ["h"], "plane_a_bp": 0, "plane_b_bp": 8, "target_twist_deg": -20.0},
    "loop-skip-bend": {"helix_ids": ["h"], "plane_a_bp": 0, "plane_b_bp": 8, "radius_nm": 100.0, "direction_deg": 90.0},
    "loop-skip-clear": {"helix_ids": ["h"], "plane_a_bp": 0, "plane_b_bp": 8},
    "loop-skip-clear-all": {},
}


def saved(kind):
    return {"_proof_version": 1, **deepcopy(CASES[kind])}


def api():
    from backend.api import part_routing_edit_inputs
    return part_routing_edit_inputs


def test_catalog_is_all_twenty_two_native_roles():
    assert api().KINDS == frozenset(CASES)


@pytest.mark.parametrize("kind", CASES)
def test_all_native_roles_keep_complete_detached_inputs(kind):
    previous = saved(kind)
    before = deepcopy(previous)
    result = api().normalize(kind, previous, {})
    assert result == before
    assert result is not previous
    for key, value in result.items():
        if isinstance(value, (dict, list)):
            assert value is not previous[key]
    assert previous == before


@pytest.mark.parametrize("kind, patch", [
    ("nick", {"direction": []}), ("nick", {"bp_index": True}),
    ("domain-shift", {"entries": [{"strand_id": "s", "domain_index": -1, "delta_bp": 2}]}),
    ("strand-end-resize", {"entries": [{"strand_id": "s", "helix_id": "h", "end": "3p", "delta_bp": "2"}]}),
    ("forced-ligation-create", {"is_periodic_seam": 1}),
    ("crossover-place", {"half_a": {"helix_id": "h", "index": 3, "strand": "FORWARD", "future": 1}}),
    ("crossover-place", {"process_id": 7}),
    ("crossover-move", {"new_index": 1.0}),
    ("loop-skip-insert", {"delta": 2}),
    ("loop-skip-bend", {"radius_nm": 0}),
    ("loop-skip-twist", {"target_twist_deg": float("inf")}),
    ("loop-skip-clear", {"helix_ids": [""]}),
    ("loop-skip-clear-all", {"helix_ids": []}),
])
def test_malformed_native_fields_refuse_without_coercion(kind, patch):
    with pytest.raises(CommandContractError):
        api().normalize(kind, saved(kind), patch)


@pytest.mark.parametrize("field,value", [("future", 1), ("_generator", {}), ("_generated_scope", {})])
def test_unknown_previous_fields_are_not_discarded(field, value):
    with pytest.raises(CommandContractError):
        api().normalize("nick", {**saved("nick"), field: value}, {})


@pytest.mark.parametrize("version", [None, True, 2, "1"])
def test_only_exact_saved_native_version_one_is_editable(version):
    with pytest.raises(CommandContractError):
        api().normalize("nick", {**saved("nick"), "_proof_version": version}, {})


@pytest.mark.parametrize("kind,field,value", [
    ("nick", "_proof_version", 2),
    ("crossover-place", "crossover_id", X2),
    ("forced-ligation-create", "_fl_id", "different"),
])
def test_protected_contract_and_single_output_ids_cannot_be_rewritten(kind, field, value):
    with pytest.raises(CommandContractError):
        api().normalize(kind, saved(kind), {field: value})


@pytest.mark.parametrize("kind", ["crossover-move", "crossover-delete", "crossover-extra-bases"])
def test_crossover_consumers_edit_reference_and_identity_helper_agrees(kind):
    from backend.core.part_edit_identity import preserve_proof_identity

    old = saved(kind)
    new = api().normalize(kind, old, {"crossover_id": X2})
    assert new["crossover_id"] == X2
    assert preserve_proof_identity(old, new, kind=kind)["crossover_id"] == X2
    assert old["crossover_id"] == X1


def test_native_defaults_and_empty_sequences_are_preserved():
    old = saved("crossover-place")
    del old["process_id"]
    assert api().normalize("crossover-place", old, {})["process_id"] == "manual"
    assert api().normalize("crossover-place", old, {"process_id": None})["process_id"] is None
    old = saved("forced-ligation-create")
    del old["is_periodic_seam"]
    assert api().normalize("forced-ligation-create", old, {})["is_periodic_seam"] is False
    for kind in ("crossover-extra-bases", "forced-ligation-extra-bases"):
        assert api().normalize(kind, saved(kind), {"sequence": "aCgtn"})["sequence"] == "ACGTN"
        assert api().normalize(kind, saved(kind), {"sequence": ""})["sequence"] == ""


def test_batch_sequence_validates_even_an_earlier_superseded_item():
    patch = {"entries": [{"crossover_id": X1, "sequence": "BAD"}, {"crossover_id": X1, "sequence": "AC"}]}
    with pytest.raises(CommandContractError):
        api().normalize("crossover-extra-bases-batch", saved("crossover-extra-bases-batch"), patch)
    patch["entries"][0]["sequence"] = "tt"
    result = api().normalize("crossover-extra-bases-batch", saved("crossover-extra-bases-batch"), patch)
    assert result["entries"] == [{"crossover_id": X1, "sequence": "TT"}, {"crossover_id": X1, "sequence": "AC"}]


def test_native_duplicate_deletion_and_ordered_nicks_are_not_universally_deduplicated():
    for kind, field, value in [("crossover-delete-batch", "crossover_ids", X1),
                               ("forced-ligation-delete-batch", "forced_ligation_ids", "fl"),
                               ("nick-batch", "nicks", CASES["nick"])]:
        result = api().normalize(kind, saved(kind), {field: [deepcopy(value), deepcopy(value)]})
        assert result[field] == [value, value]


def test_batch_output_slots_follow_identity_through_reorder_and_removal():
    old = {"_proof_version": 1, "placements": [placement(X1), placement(X2)]}
    swapped = [placement(X2), {**placement(X1), "nick_bp_a": 7}]
    result = api().normalize("crossover-place-batch", old, {"placements": swapped})
    assert result["placements"] == swapped
    assert api().normalize("crossover-place-batch", old, {"placements": [placement(X2)]})["placements"] == [placement(X2)]
    assert api().normalize("crossover-place-batch", old, {"placements": []})["placements"] == []


@pytest.mark.parametrize("new_slot", ["omitted", "null"])
def test_new_output_slots_are_allocated_once_and_need_exact_private_receipt(new_slot):
    fresh = placement(None)
    if new_slot == "omitted":
        del fresh["crossover_id"]
    changes = {"placements": [fresh, placement(X1)]}
    before = deepcopy(changes)
    allocated = api().allocate_output_slots("crossover-place-batch", saved("crossover-place-batch"), changes)
    assert set(allocated) == {"changes", "added_ids"}
    new_id, = allocated["added_ids"]
    assert str(UUID(new_id)) == new_id and new_id != X1
    assert allocated["changes"]["placements"][0]["crossover_id"] == new_id
    assert changes == before
    with pytest.raises(CommandContractError):
        api().normalize("crossover-place-batch", saved("crossover-place-batch"), allocated["changes"])
    result = api().normalize("crossover-place-batch", saved("crossover-place-batch"),
                             allocated["changes"], added_output_ids=allocated["added_ids"])
    assert [item["crossover_id"] for item in result["placements"]] == [new_id, X1]
    with pytest.raises(CommandContractError):
        api().normalize("crossover-place-batch", saved("crossover-place-batch"),
                        allocated["changes"], added_output_ids=[new_id, X3])


@pytest.mark.parametrize("placements", [[placement(X3)], [placement(X1), placement(X1)]])
def test_allocator_refuses_client_replacement_ids_or_duplicate_retained_outputs(placements):
    with pytest.raises(CommandContractError):
        api().allocate_output_slots("crossover-place-batch", saved("crossover-place-batch"), {"placements": placements})


def test_alias_expansion_is_bounded_before_detaching(monkeypatch):
    module = api()
    monkeypatch.setattr(module, "deepcopy", lambda *_: pytest.fail("copied over-budget input"))
    with pytest.raises(CommandContractError):
        module.normalize("crossover-place-batch", saved("crossover-place-batch"), {"placements": [placement()] * 5000})


@pytest.mark.parametrize("kind,patch", [
    ("strand-end-resize", {"entries": [{"strand_id": "s", "helix_id": "h", "end": "3p", "delta_bp": 50_001}]}),
    ("domain-shift", {"entries": [{"strand_id": "s", "domain_index": 0, "delta_bp": -25_001}] * 2}),
    ("loop-skip-twist", {"plane_b_bp": 25_001, "helix_ids": ["h", "other"]}),
    ("loop-skip-bend", {"plane_b_bp": 50_001}),
])
def test_prospective_native_work_is_bounded_before_execution(kind, patch):
    with pytest.raises(CommandContractError) as caught:
        api().normalize(kind, saved(kind), patch)
    assert caught.value.code == "routing_input_limit"


@pytest.fixture
def prefix():
    from backend.core.models import Crossover, Domain, ForcedLigation, Helix, Strand, Vec3
    from backend.core.part_history_contract import create_empty_part

    helices = [Helix(id=hid, axis_start=Vec3(x=x, y=0, z=0), axis_end=Vec3(x=x, y=0, z=3.06), length_bp=10)
               for hid, x in (("h", 0), ("other", 2.5))]
    strands = [Strand(id=sid, domains=[Domain(helix_id=hid, start_bp=0, end_bp=9, direction="FORWARD")])
               for sid, hid in (("s", "h"), ("second", "other"))]
    return create_empty_part("Routing inputs", "SQUARE").copy_with(helices=helices, strands=strands,
        crossovers=[Crossover(id=X1, half_a=placement()["half_a"], half_b=placement()["half_b"])],
        forced_ligations=[ForcedLigation(id="fl", three_prime_helix_id="h", three_prime_bp=9,
            three_prime_direction="FORWARD", five_prime_helix_id="other", five_prime_bp=0,
            five_prime_direction="FORWARD")])


@pytest.mark.parametrize("kind,patch,resource,identity,path", [
    ("nick", {"helix_id": "gone"}, "helix", "gone", ["helix_id"]),
    ("nick-batch", {"nicks": [{**CASES["nick"], "helix_id": "gone"}]}, "helix", "gone", ["nicks", 0, "helix_id"]),
    ("ligate", {"helix_id": "gone"}, "helix", "gone", ["helix_id"]),
    ("domain-shift", {"entries": [{"strand_id": "s", "domain_index": 1, "delta_bp": 1}]}, "domain", "s:1", ["entries", 0, "domain_index"]),
    ("forced-ligation-create", {"five_prime_strand_id": "gone"}, "strand", "gone", ["five_prime_strand_id"]),
    ("forced-ligation-delete-batch", {"forced_ligation_ids": ["fl", "gone"]}, "forced_ligation", "gone", ["forced_ligation_ids", 1]),
    ("crossover-move-batch", {"moves": [{"crossover_id": "gone", "new_index": 3}]}, "crossover", "gone", ["moves", 0, "crossover_id"]),
    ("crossover-extra-bases-batch", {"entries": [{"crossover_id": "gone", "sequence": "A"}]}, "crossover", "gone", ["entries", 0, "crossover_id"]),
    ("loop-skip-twist", {"helix_ids": ["h", "gone"]}, "helix", "gone", ["helix_ids", 1]),
])
def test_pre_child_references_report_exact_authored_paths(prefix, kind, patch, resource, identity, path):
    before = prefix.model_dump_json()
    params = api().normalize(kind, saved(kind), patch)
    with pytest.raises(ReferenceResolutionError) as caught:
        api().bind_prefix(kind, params, prefix)
    assert caught.value.code == "missing_reference"
    assert caught.value.as_issue()["references"] == [{"kind": resource, "identity": identity, "parameter_path": path}]
    assert prefix.model_dump_json() == before


def test_terminal_validation_and_duplicate_source_identity_are_explicit(prefix):
    values = saved("strand-end-resize")
    values["entries"][0]["helix_id"] = "other"
    with pytest.raises(ReferenceResolutionError) as caught:
        api().bind_prefix("strand-end-resize", values, prefix)
    assert caught.value.code == "invalid_selection"
    prefix.helices.append(prefix.helices[0].model_copy())
    with pytest.raises(ReferenceResolutionError) as caught:
        api().bind_prefix("nick", saved("nick"), prefix)
    assert caught.value.code == "invalid_selection"


def test_clear_retains_native_empty_interval_and_stale_mark_semantics(prefix):
    from backend.api.part_proof_commands import execute
    from backend.core.models import LoopSkip

    prefix.helices[0].loop_skips = [LoopSkip(bp_index=99, delta=1), LoopSkip(bp_index=3, delta=-1)]
    patch = {"bp_index": 99, "delta": 0}
    inputs = api().normalize("loop-skip-insert", saved("loop-skip-insert"), patch)
    bound = api().bind_prefix("loop-skip-insert", inputs, prefix)
    result = execute("loop-skip-insert", prefix, bound)
    assert [mark.bp_index for mark in result.helices[0].loop_skips] == [3]
    clear = api().normalize("loop-skip-clear", saved("loop-skip-clear"), {"plane_a_bp": 8, "plane_b_bp": 0})
    result = execute("loop-skip-clear", prefix, api().bind_prefix("loop-skip-clear", clear, prefix))
    assert result.helices == prefix.helices
    assert api().bind_prefix("loop-skip-clear-all", {"_proof_version": 1}, prefix) == {"_proof_version": 1}
