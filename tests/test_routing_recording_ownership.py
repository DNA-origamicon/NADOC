"""Ordinary loop edits and crossover moves record exactly their locked source."""

import pytest
from fastapi import HTTPException

from backend.api import crud, part_crossover_moves, routes_loop_skip, state
from backend.core import loop_skip_calculator
from backend.core.models import Design, DesignLoadout, LoopSkip
from tests.test_geometry_routing_recording import (
    _GuardedLock, _authoring, _signature, _verified, document as document,
)
from tests.test_group_lineage_crossovers import placement
from backend.core.positional_refs import KINDS as POSITIONAL


KINDS = ("loop-skip-insert", "loop-skip-twist", "loop-skip-bend",
         "crossover-move", "crossover-move-batch")


def arrange(document, kind):
    if kind.startswith("crossover"):
        crud.place_crossover(crud.PlaceCrossoverRequest(**placement(document)))
    return state.get_or_404()


def invoke(kind, source, *, no_op=False, missing=False):
    if kind == "loop-skip-insert":
        return routes_loop_skip.insert_loop_skip(routes_loop_skip.LoopSkipInsertRequest(
            helix_id="missing" if missing else source.helices[0].id, bp_index=10, delta=1))
    if kind.startswith("loop-skip"):
        params = {"helix_ids": [h.id for h in source.helices] + (["missing"] if missing else []),
                  "plane_a_bp": 0, "plane_b_bp": 35}
        if kind == "loop-skip-twist":
            return routes_loop_skip.apply_twist_loop_skips({**params, "target_twist_deg": 20.0})
        return routes_loop_skip.apply_bend_loop_skips({**params, "radius_nm": 100.0, "direction_deg": 0.0})
    target = source.crossovers[0]
    params = {"crossover_id": "missing" if missing else target.id,
              "new_index": target.half_a.index if no_op else target.half_a.index + 21}
    if kind.endswith("-batch"):
        return crud.batch_move_crossovers(crud.BatchMoveCrossoversRequest(moves=[params]))
    return crud.move_crossover_endpoint(crud.MoveCrossoverRequest(**params))


def native_slot(kind):
    if kind.startswith("loop-skip"):
        return loop_skip_calculator, "apply_loop_skips"
    return part_crossover_moves, "batch_move" if kind.endswith("-batch") else "move"


@pytest.mark.parametrize("kind", KINDS)
def test_native_builder_runs_once_within_one_non_reentrant_recording_lock(document, kind, monkeypatch):
    from backend.core import part_history_contract

    source = arrange(document, kind)
    lock, calls = _GuardedLock(), []
    module, name = native_slot(kind)
    original = getattr(module, name)

    def native(design, *args, **kwargs):
        assert lock.held, "native routing ran outside its recording lock"
        calls.append(design)
        return original(design, *args, **kwargs)

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(module, name, native)
        hooks.setattr(part_history_contract, "assess_part_history",
                      lambda *_a, **_k: pytest.fail("ordinary edit ran full proof"))
        invoke(kind, source)
    assert calls == [source]
    assert not lock.held


@pytest.mark.parametrize("kind", KINDS)
def test_edit_after_first_lock_release_survives_the_authored_operation(document, kind, monkeypatch):
    source = arrange(document, kind)
    third = next(s for s in source.strands if s.strand_type == "staple"
                 and s.domains[0].helix_id == source.helices[2].id)
    domain = third.domains[0]
    before_depth, before_revision = state.undo_depth(), state.revision()

    def concurrent_nick():
        crud.add_nick(crud.NickRequest(helix_id=domain.helix_id, bp_index=12,
                                      direction=domain.direction))

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", _GuardedLock(concurrent_nick))
        invoke(kind, source)
    current = state.get_or_404()
    fragments = [s for s in current.strands if s.strand_type == "staple"
                 and any(d.helix_id == domain.helix_id for d in s.domains)]
    assert len(fragments) == 2, "The owned edit overwrote the interleaved native nick"
    assert state.undo_depth() == before_depth + 2 and state.revision() == before_revision + 2
    _verified(current)


@pytest.mark.parametrize("kind", KINDS)
def test_ordinary_edit_records_one_native_child_and_undo_reload_cold_prove(document, kind):
    source = arrange(document, kind)
    before = _authoring(source)
    depth, revision = state.undo_depth(), state.revision()
    result = invoke(kind, source)
    current = state.get_or_404()
    row = current.feature_log[-1].children[-1]
    # Crossover edits record the junction by position (proof v2; see positional_refs).
    assert row.op_subtype == kind and row.params["_proof_version"] == (2 if kind in POSITIONAL else 1)
    assert state.undo_depth() == depth + 1 and state.revision() == revision + 1 == result["revision"]
    if kind.startswith("crossover"):
        assert result["partial_geometry"] is True
        assert set(result["changed_helix_ids"]) == {source.helices[0].id, source.helices[1].id}
    elif kind != "loop-skip-insert":
        assert set(result["loop_skips"]) == {h.id for h in source.helices}
    saved = Design.model_validate_json(current.model_dump_json())
    _verified(saved)
    restored, _ = state.undo()
    assert _authoring(restored) == before
    restored, _ = state.redo()
    assert _authoring(restored) == _authoring(saved)
    _verified(restored)


@pytest.mark.parametrize("kind", ["crossover-move", "crossover-move-batch"])
def test_noop_move_still_checks_source_once_and_does_not_record(document, kind, monkeypatch):
    source = arrange(document, kind)
    before = _signature()
    lock, calls = _GuardedLock(), []
    module, name = native_slot(kind)
    original = getattr(module, name)

    def native(design, *args, **kwargs):
        assert lock.held
        calls.append(design)
        return original(design, *args, **kwargs)

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "_lock", lock)
        hooks.setattr(module, name, native)
        response = invoke(kind, source, no_op=True)
    assert calls == [source] and _signature() == before
    assert response["design"]["id"] == source.id
    assert response.get("partial_geometry", False) is False


@pytest.mark.parametrize("kind", KINDS)
def test_protected_loadout_rejects_before_native_even_for_move_noop(document, kind, monkeypatch):
    source = arrange(document, kind)
    loadout = DesignLoadout(name="Protected", protected=True)
    source = source.copy_with(loadouts=[loadout], active_loadout_id=loadout.id)
    state.load_design(source)
    before = _signature()
    module, name = native_slot(kind)
    with monkeypatch.context() as hooks:
        hooks.setattr(module, name, lambda *_a, **_k: pytest.fail("protected source reached builder"))
        with pytest.raises(HTTPException) as caught:
            invoke(kind, source, no_op=True)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "protected_simulation_loadout"
    assert _signature() == before


@pytest.mark.parametrize("kind", KINDS)
def test_missing_target_never_records_a_partial_selection(document, kind):
    source = arrange(document, kind)
    before = _signature()
    with pytest.raises(HTTPException) as caught:
        invoke(kind, source, missing=True)
    assert caught.value.status_code == 404
    assert _signature() == before


@pytest.mark.parametrize("kind", ["twist", "bend"])
def test_empty_selection_retains_existing_refusal(document, kind):
    before = _signature()
    call = getattr(routes_loop_skip, f"apply_{kind}_loop_skips")
    params = {"helix_ids": [], "plane_a_bp": 0, "plane_b_bp": 35,
              **({"target_twist_deg": 20} if kind == "twist" else {"radius_nm": 100})}
    with pytest.raises(HTTPException) as caught:
        call(params)
    assert caught.value.status_code == 422
    assert caught.value.detail == "No valid helix_ids provided."
    assert _signature() == before


@pytest.mark.parametrize("kind", ["twist", "bend"])
def test_native_empty_interval_still_records_empty_modifications(document, kind):
    before = _authoring(document)
    depth = state.undo_depth()
    call = getattr(routes_loop_skip, f"apply_{kind}_loop_skips")
    hid = document.helices[0].id
    response = call({"helix_ids": [hid], "plane_a_bp": 10, "plane_b_bp": 10,
        **({"target_twist_deg": 20} if kind == "twist" else {"radius_nm": 100})})
    assert response["loop_skips"] == {hid: []}
    assert _authoring(state.get_or_404()) == before
    assert state.undo_depth() == depth + 1
    _verified(state.get_or_404())


def test_zero_delta_can_still_remove_a_stale_out_of_range_mark(document):
    # This deliberately malformed saved mark is a legacy cleanup control, not
    # a native recipe or permission to insert an out-of-range loop.
    helix = document.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=999, delta=1)]})
    source = document.copy_with(helices=[helix, *document.helices[1:]])
    state.load_design(source)
    depth = state.undo_depth()
    routes_loop_skip.insert_loop_skip(routes_loop_skip.LoopSkipInsertRequest(
        helix_id=helix.id, bp_index=999, delta=0))
    assert not state.get_or_404().helices[0].loop_skips
    assert state.undo_depth() == depth + 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("stage", ["validation", "publication", "cancellation"])
def test_failure_restores_design_stacks_and_request_markers(document, kind, stage, monkeypatch):
    source = arrange(document, kind)
    state._session().redo.append(Design())
    before = _signature()
    exception = KeyboardInterrupt if stage == "cancellation" else RuntimeError
    original_bump = state._bump_revision

    def fail(*_a, **_k):
        raise exception("owned routing failure")

    def bump(session):
        original_bump(session)
        fail()

    with monkeypatch.context() as hooks:
        hooks.setattr(state, "validate_design" if stage == "validation" else "_bump_revision",
                      fail if stage == "validation" else bump)
        with pytest.raises(exception, match="owned routing failure"):
            invoke(kind, source)
    assert _signature() == before
