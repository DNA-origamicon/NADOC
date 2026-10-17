"""All native Fine Routing child roles cross the owned editor boundary.

Only the process transport is controlled: the real proof/evaluator, native
builders, publication, history reconstruction and cold proof all execute.
Native crossover fixtures use the existing HC lookup-table/nick conventions.
"""

from collections import Counter
from copy import deepcopy
import json
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, part_proof_commands as commands, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.core import models as m
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import create_empty_part
from tests.test_group_lineage_crossovers import placement
from tests.test_group_lineage_transforms import organize
from tests.test_part_deformation_preview import _append, authoring
from tests.test_part_pattern_recording import saved, unchanged, worker
from tests.test_part_routing_owned_edit import _verified, host
from tests.test_part_transform_preview import snapshot

__all__ = ["worker"]

KINDS = (
    "strand-end-resize", "domain-shift", "nick", "nick-batch", "ligate",
    "forced-ligation-create", "forced-ligation-delete", "forced-ligation-delete-batch",
    "forced-ligation-extra-bases", "crossover-place", "crossover-place-batch",
    "crossover-move", "crossover-move-batch", "crossover-delete", "crossover-delete-batch",
    "crossover-extra-bases", "crossover-extra-bases-batch", "loop-skip-insert",
    "loop-skip-twist", "loop-skip-bend", "loop-skip-clear",
)
FIRST, SECOND = str(UUID(int=28011)), str(UUID(int=28012))
SUFFIX = {"cells": [[14, 14]], "length_bp": 3, "plane": "XY", "history_seed": str(UUID(int=28002))}


def base(organized):
    source = snapshot(create_empty_part("Routing native matrix", "HONEYCOMB"), "bundle-create",
        crud.BundleRequest(cells=[[0, 0], [0, 1], [4, 0], [4, 1], [8, 0], [8, 1]],
            length_bp=70, ligate_adjacent=False, history_seed=UUID(int=28001)).model_dump(mode="json"), "bundle")
    return organize(source, append=True) if organized else source


def crossover_inputs(source, *, index=7):
    return [placement(source, index, pair=pair, identity=identity)
            for pair, identity in (((0, 1), 28011), ((2, 3), 28012))]


def prepared_case(kind, organized):
    """Return actual pre-child topology, original inputs and a meaningful edit."""
    source = base(organized)
    h = source.helices[0].id
    forward = next(s for s in source.strands if s.domains[0].helix_id == h
                   and s.domains[0].direction == m.Direction.FORWARD)
    site = {"helix_id": h, "bp_index": 8, "direction": "FORWARD"}
    if kind == "strand-end-resize":
        entry = {"strand_id": forward.id, "helix_id": h, "end": "3p", "delta_bp": -2}
        original, patch = {"entries": [entry]}, {"entries": [{**entry, "delta_bp": -4}]}
    elif kind == "domain-shift":
        entry = {"strand_id": forward.id, "domain_index": 0, "delta_bp": 1}
        original, patch = {"entries": [entry]}, {"entries": [{**entry, "delta_bp": 2}]}
    elif kind == "nick":
        original, patch = site, {"bp_index": 12}
    elif kind == "nick-batch":
        original = {"nicks": [site, {**site, "bp_index": 20}]}
        patch = {"nicks": [{**site, "bp_index": 12}, {**site, "bp_index": 24}]}
    elif kind == "ligate":
        source = snapshot(source, "nick-batch", {"nicks": [site, {**site, "bp_index": 20}]}, "prior-nicks")
        original, patch = site, {"bp_index": 20}
    elif kind.startswith("forced-ligation"):
        scaffold_ids = [s.id for s in source.strands if s.strand_type == m.StrandType.SCAFFOLD]
        first = {"three_prime_strand_id": scaffold_ids[0], "five_prime_strand_id": scaffold_ids[1],
                 "_fl_id": "forced-first", "is_periodic_seam": False}
        second = {"three_prime_strand_id": scaffold_ids[2], "five_prime_strand_id": scaffold_ids[3],
                  "_fl_id": "forced-second", "is_periodic_seam": False}
        if kind == "forced-ligation-create":
            original, patch = first, {"five_prime_strand_id": scaffold_ids[2], "is_periodic_seam": True}
        else:
            source = snapshot(snapshot(source, "forced-ligation-create", first, "prior-forced-first"),
                              "forced-ligation-create", second, "prior-forced-second")
            if kind == "forced-ligation-delete":
                original, patch = {"fl_id": first["_fl_id"]}, {"fl_id": second["_fl_id"]}
            elif kind.endswith("delete-batch"):
                original = {"forced_ligation_ids": [first["_fl_id"]]}
                patch = {"forced_ligation_ids": [first["_fl_id"], second["_fl_id"]]}
            else:
                original = {"fl_id": first["_fl_id"], "sequence": "TT"}
                patch = {"fl_id": second["_fl_id"], "sequence": "ACG"}
    elif kind.startswith("crossover"):
        first, second = crossover_inputs(source)
        if kind == "crossover-place":
            original, patch = first, crossover_inputs(source, index=28)[0]
        elif kind == "crossover-place-batch":
            original = {"placements": [first, second]}
            patch = {"placements": list(reversed(crossover_inputs(source, index=28)))}
        else:
            source = snapshot(source, "crossover-place-batch", {"placements": [first, second]}, "prior-crossovers")
            if kind == "crossover-move":
                original = {"crossover_id": FIRST, "new_index": 28}
                patch = {"crossover_id": SECOND, "new_index": 49}
            elif kind == "crossover-move-batch":
                original = {"moves": [{"crossover_id": FIRST, "new_index": 28}, {"crossover_id": SECOND, "new_index": 28}]}
                patch = {"moves": [{"crossover_id": SECOND, "new_index": 49}, {"crossover_id": FIRST, "new_index": 49}]}
            elif kind == "crossover-delete":
                original, patch = {"crossover_id": FIRST}, {"crossover_id": SECOND}
            elif kind == "crossover-delete-batch":
                original, patch = {"crossover_ids": [FIRST]}, {"crossover_ids": [FIRST, SECOND]}
            elif kind == "crossover-extra-bases":
                original, patch = {"crossover_id": FIRST, "sequence": "TT"}, {"crossover_id": SECOND, "sequence": "ACG"}
            else:
                original = {"entries": [{"crossover_id": FIRST, "sequence": "TT"}, {"crossover_id": SECOND, "sequence": "A"}]}
                patch = {"entries": [{"crossover_id": SECOND, "sequence": "ACG"},
                                     {"crossover_id": FIRST, "sequence": "G"},
                                     {"crossover_id": SECOND, "sequence": "TTT"}]}
    else:
        scope = {"helix_ids": [item.id for item in source.helices], "plane_a_bp": 0, "plane_b_bp": 63}
        if kind == "loop-skip-insert":
            original = {"helix_id": h, "bp_index": 10, "delta": 1}
            patch = {"helix_id": source.helices[1].id, "bp_index": 14, "delta": -1}
        elif kind == "loop-skip-twist":
            original, patch = {**scope, "target_twist_deg": 40.0}, {"target_twist_deg": -40.0}
        elif kind == "loop-skip-bend":
            original = {**scope, "radius_nm": 100.0, "direction_deg": 0.0}
            patch = {"radius_nm": 200.0, "direction_deg": 90.0}
        else:
            for index, bp in ((0, 10), (1, 35)):
                source = snapshot(source, "loop-skip-insert", {"helix_id": source.helices[index].id,
                    "bp_index": bp, "delta": 1}, f"prior-loop-{index}")
            original = {"helix_ids": [h], "plane_a_bp": 0, "plane_b_bp": 21}
            patch = scope
    return source, {"_proof_version": 1, **original}, patch


def parent(source, rows, identity="selected-parent"):
    log, children = list(source.feature_log), []
    for kind, params, child_id in rows:
        params = {"_proof_version": 1, **params}
        source = commands.execute(kind, source, params)
        children.append(m.MinorMutationLogEntry(id=child_id, op_subtype=kind, label=kind,
            params=params, diff_added_b64="poisoned-diff"))
    row = m.RoutingClusterLogEntry(id=identity, children=children, diffs_evicted=True,
        pre_state_gz_b64="poisoned-pre", post_state_gz_b64="poisoned-post")
    return source.copy_with(feature_log=[*log, row])


def later_deformation(source):
    operation = m.DeformationOp(id="later-bend", type="bend", plane_a_bp=14, plane_b_bp=56,
        affected_helix_ids=[h.id for h in source.helices], cluster_ids=[],
        params={"kind": "bend", "curvature_deg_per_bp": .03, "direction_deg": 20.0})
    return _append(source, m.DeformationLogEntry(id="later-bend-row", deformation_id=operation.id,
        op_snapshot=operation, proof_version=1))


def with_suffix(source):
    return snapshot(later_deformation(source), "extrude-segment", SUFFIX, "later-extrusion")


@pytest.fixture
def document(monkeypatch):
    doc = f"__routing_native_matrix__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    markers = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    try:
        def install(source):
            state.load_design(source)
            return state._sessions[doc]
        yield install
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])


def edit(session, index, patch, sub_index=0):
    row = session.design.feature_log[index]
    return host().edit_routing(index, sub_index, patch, expected_design_id=session.design.id,
        expected_revision=session.revision, expected_feature_id=row.id,
        expected_child_id=row.children[sub_index].id)


def native_parity(actual, expected):
    assert authoring(actual) == authoring(expected)
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)


def recovered_native_parity(actual, expected):
    # Recorded diffs append newly created strands; the native nick builder
    # inserts them at the replaced strand's position. Recovery equivalence
    # therefore compares this top-level collection by identity only. Every
    # complete strand, including its ordered domains, must still match. Native
    # final recipe proof above continues to require exact authoring list order.
    left, right = authoring(actual), authoring(expected)
    for value in (left, right):
        strands = value["strands"]
        assert len({strand["id"] for strand in strands}) == len(strands)
        value["strands"] = {strand["id"]: strand for strand in strands}
    assert left == right
    # Compare complete native records, including stable residue/strand IDs and
    # all coordinates, with multiplicity. No coordinate tolerance or domain
    # sorting may hide a material difference in the reconstructed state.
    records = lambda design: Counter(json.dumps(record, sort_keys=True, allow_nan=False)
                                     for record in _geometry_for_design(design))
    assert records(actual) == records(expected)
    assert deformed_helix_axes(actual) == deformed_helix_axes(expected)


def test_catalog_accounts_for_every_editable_role_and_no_input_clear_all():
    from backend.api.part_routing_edit_inputs import KINDS as actual
    assert actual == frozenset(KINDS) | {"loop-skip-clear-all"}


@pytest.mark.parametrize("organized", [False, True], ids=["legacy", "organized"])
@pytest.mark.parametrize("kind", KINDS)
def test_every_native_edit_changes_inputs_and_material_rebuilds_suffix_reload_and_undo(
    kind, organized, document, worker
):
    prefix, original, patch = prepared_case(kind, organized)
    index = len(prefix.feature_log)
    sibling = {"helix_id": prefix.helices[-1].id, "bp_index": 60, "direction": "FORWARD"}
    source = with_suffix(parent(prefix, [(kind, original, "selected-child"), ("nick", sibling, "later-child")]))
    _verified(source)
    before_prefix = prefix.model_dump_json()
    expected = commands.execute(kind, prefix, {**original, **patch})
    expected = commands.execute("nick", expected, {"_proof_version": 1, **sibling})
    expected = with_suffix(expected)
    assert authoring(expected) != authoring(source), "Fixture must exercise an actual native material change"
    session = document(source)
    before = saved(session)
    candidate, report, row = edit(session, index, patch)
    assert report.passed and candidate is session.design
    assert row.id == "selected-parent" and [child.id for child in row.children] == ["selected-child", "later-child"]
    assert row.children[0].params == {**original, **patch}
    assert row.children[1].params == source.feature_log[index].children[1].params
    assert candidate.feature_log[-2].op_snapshot == source.feature_log[-2].op_snapshot
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    native_parity(candidate, expected)
    assert prefix.model_dump_json() == before_prefix and source.model_dump_json() == before[1]
    assert session.revision == before[2] + 1 and len(session.history) == len(before[3]) + 1
    restored = m.Design.model_validate_json(candidate.model_dump_json())
    native_parity(restored, expected)
    _verified(restored)
    state.undo()
    assert session.design.model_dump_json() == before[1]
    state.redo()
    native_parity(session.design, expected)


@pytest.mark.parametrize("organized", [False, True], ids=["legacy", "organized"])
def test_clear_all_is_no_input_but_rebuilds_after_real_upstream_loop_edit(organized, document, worker):
    prefix = base(organized)
    original = {"helix_id": prefix.helices[0].id, "bp_index": 10, "delta": 1}
    index = len(prefix.feature_log)
    source = parent(prefix, [("loop-skip-insert", original, "selected-loop"),
                             ("loop-skip-clear-all", {}, "clear-all")])
    session = document(source)
    row = source.feature_log[index]
    before = saved(session)
    packet = host().routing_inputs(index, 1, expected_design_id=source.id,
        expected_revision=session.revision, expected_feature_id=row.id, expected_child_id="clear-all")
    assert packet["params"] == {"_proof_version": 1}
    unchanged(session, before)
    candidate, report, row = edit(session, index, {"bp_index": 14, "delta": -1})
    assert report.passed and row.children[1].params == {"_proof_version": 1}
    assert not any(h.loop_skips for h in candidate.helices)
    _verified(candidate)
    middle = crud._seek_feature_log(candidate, index, 0, optimized=False)
    assert middle.helices[0].loop_skips == [m.LoopSkip(bp_index=14, delta=-1)]
    assert not any(h.loop_skips for h in crud._seek_feature_log(candidate, -1).helices)


@pytest.mark.parametrize("organized", [False, True], ids=["legacy", "organized"])
def test_batch_creation_add_remove_reorder_preserves_slots_and_later_consumer(organized, document, worker):
    prefix = base(organized)
    first, second = crossover_inputs(prefix)
    index = len(prefix.feature_log)
    source = parent(prefix, [("crossover-place-batch", {"placements": [first, second]}, "selected-child"),
        ("crossover-extra-bases", {"crossover_id": SECOND, "sequence": "AT"}, "dependent-child")])
    session = document(source)
    new_slot = placement(prefix, 7, pair=(4, 5), identity=28013)
    del new_slot["crossover_id"]
    changed_first = crossover_inputs(prefix, index=28)[0]
    patch = {"placements": [second, new_slot, changed_first]}
    input_copy = deepcopy(patch)
    candidate, report, row = edit(session, index, patch)
    assert report.passed and patch == input_copy
    entries = row.children[0].params["placements"]
    new_id = entries[1]["crossover_id"]
    assert str(UUID(new_id)) == new_id and new_id not in {FIRST, SECOND}
    assert [entry["crossover_id"] for entry in entries] == [SECOND, new_id, FIRST]
    assert [item.id for item in candidate.crossovers] == [SECOND, new_id, FIRST]
    assert next(item for item in candidate.crossovers if item.id == SECOND).extra_bases == "AT"
    expected = commands.execute("crossover-place-batch", prefix, row.children[0].params)
    expected = commands.execute("crossover-extra-bases", expected, row.children[1].params)
    native_parity(candidate, expected)
    _verified(m.Design.model_validate_json(candidate.model_dump_json()))
    # Remove an unconsumed old slot and reorder the retained new slot. It must
    # retain its accepted ID, rather than allocate another ID at its new index.
    candidate, report, row = edit(session, index, {"placements": [entries[1], entries[0]]})
    assert report.passed
    assert [entry["crossover_id"] for entry in row.children[0].params["placements"]] == [new_id, SECOND]
    assert {item.id for item in candidate.crossovers} == {new_id, SECOND}
    _verified(candidate)
    session.redo.append(m.Design())
    before = saved(session)
    with pytest.raises(HTTPException) as caught:
        edit(session, index, {"placements": [row.children[0].params["placements"][0]]})
    assert caught.value.status_code == 409 and "dependent-child" in str(caught.value.detail)
    unchanged(session, before)


@pytest.mark.parametrize("organized", [False, True], ids=["legacy", "organized"])
def test_upstream_loop_edit_rebuilds_native_deformation_realization_suffix(organized, document, worker):
    prefix = base(organized)
    prefix = snapshot(prefix, "crossover-place-batch", {"placements": crossover_inputs(prefix)}, "prior-crossovers")
    index = len(prefix.feature_log)
    original = {"helix_id": prefix.helices[-1].id, "bp_index": 65, "delta": 1}
    source = parent(prefix, [("loop-skip-insert", original, "selected-loop")])
    operation = m.DeformationOp(id="realized-twist", type="twist", plane_a_bp=14, plane_b_bp=63,
        affected_helix_ids=[h.id for h in prefix.helices], cluster_ids=[],
        params={"kind": "twist", "total_degrees": 50.0})
    deformation = m.DeformationLogEntry(id="realized-twist-row", deformation_id=operation.id,
        op_snapshot=operation, proof_version=1)
    source = snapshot(_append(source, deformation), "apply-loop-skips", {}, "realize-loops")
    _verified(source)
    assert any(h.loop_skips for h in source.helices)
    session = document(source)
    candidate, report, row = edit(session, index, {"delta": -1})
    assert report.passed and row.children[0].params["delta"] == -1
    expected = commands.execute("loop-skip-insert", prefix, {"_proof_version": 1, **original, "delta": -1})
    expected = _append(expected, deformation)
    expected = commands.execute("apply-loop-skips", expected, {"_proof_version": 1})
    native_parity(candidate, expected)
    # The later realization intentionally recomputes all active marks. The
    # edited mark exists at its history position and is then overwritten by
    # that real native suffix; do not claim an additional final material change.
    intermediate = crud._seek_feature_log(candidate, index, 0, optimized=False)
    assert intermediate.helices[-1].loop_skips == [m.LoopSkip(bp_index=65, delta=-1)]
    assert all(mark.bp_index != 65 for helix in candidate.helices for mark in helix.loop_skips)
    assert candidate.feature_log[-1].params == source.feature_log[-1].params
    _verified(m.Design.model_validate_json(candidate.model_dump_json()))


@pytest.mark.parametrize("organized", [False, True], ids=["legacy", "organized"])
def test_edited_long_history_uses_real_optimized_child_run_and_matches_f0_middle_end(
    organized, document, worker, monkeypatch
):
    from backend.core import design_diff

    prefix = base(organized)
    index = len(prefix.feature_log)
    helix = prefix.helices[0].id
    children = [("nick", {"helix_id": helix, "bp_index": 3 + 4 * number, "direction": "FORWARD"},
                 f"ordered-nick-{number}") for number in range(12)]
    source = parent(prefix, children)
    # The top-level optimized payload lookup begins at 32 entries. Every row
    # below authors a real alternating loop/skip change, without large geometry.
    for number in range(32):
        source = snapshot(source, "loop-skip-insert", {"helix_id": prefix.helices[-1].id,
            "bp_index": 55, "delta": 1 if number % 2 else -1}, f"later-mark-{number}")
    assert len(source.feature_log) >= 32
    session = document(source)
    candidate, report, row = edit(session, index, {"bp_index": 8}, sub_index=1)
    assert report.passed and row.children[1].params["bp_index"] == 8
    _verified(m.Design.model_validate_json(candidate.model_dump_json()))
    expected_middle = prefix
    for number, (kind, params, _) in enumerate(children[:10]):
        expected_middle = commands.execute(kind, expected_middle,
            {"_proof_version": 1, **params, **({"bp_index": 8} if number == 1 else {})})
    calls, native_run = [], design_diff.apply_child_diff_run

    def observed(anchor, run):
        calls.append(len(run))
        return native_run(anchor, run)

    monkeypatch.setattr(design_diff, "apply_child_diff_run", observed)
    before = candidate.model_dump_json()
    normal_middle = crud._seek_feature_log(candidate, index, 9, optimized=False)
    assert not calls
    optimized_middle = crud._seek_feature_log(candidate, index, 9, optimized=True)
    assert calls == [10], "Exercise the actual >=8-child diff composer"
    recovered_native_parity(normal_middle, expected_middle)
    recovered_native_parity(optimized_middle, expected_middle)
    for position in (-2, -1):
        normal = crud._seek_feature_log(candidate, position, optimized=False)
        optimized = crud._seek_feature_log(candidate, position, optimized=True)
        recovered_native_parity(optimized, normal)
        if position == -2:
            assert not optimized.helices and not optimized.strands and optimized.group_organization is None
        else:
            recovered_native_parity(optimized, candidate)
    assert candidate.model_dump_json() == before
