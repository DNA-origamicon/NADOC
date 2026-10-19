"""Fine Routing commands recorded by position (proof version 2).

A (helix, bp, direction) slot holds one base of one strand, so a recorded
resize/shift/crossover edit names its target by position and resolves to
whatever strand or crossover occupies it on replay — the cadnano model — instead
of an id that an upstream routing rerun re-derives.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history
from backend.core.positional_refs import PositionNotOccupied, positions, resolve, to_positional


@pytest.fixture
def part():
    from backend.api.main import app

    identity = f"positional-refs-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    http = TestClient(app)  # no lifespan
    assert http.post("/api/design", headers=headers, json={"name": "pr", "lattice_type": "HONEYCOMB"}).status_code == 201
    cells = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
    assert http.post("/api/design/bundle", headers=headers, json={"cells": cells, "length_bp": 84, "name": "pr"}).status_code == 201
    assert http.post("/api/design/auto-scaffold-seamless", headers=headers, json={}).status_code == 200
    assert http.post("/api/design/full-autostaple", headers=headers, json={}).status_code == 200
    token = doc_context.set_current_doc(identity)
    try:
        yield http, headers
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        http.close()


def _low_staple_5p(design):
    staples = [s for s in design.strands if s.strand_type.value == "staple" and len(s.domains) >= 2]
    return min(staples, key=lambda s: max(max(d.start_bp, d.end_bp) for d in s.domains))


def _renamed(design, suffix):
    """Same topology, every staple id re-derived (what an upstream routing rerun may do)."""
    return design.model_copy(update={"strands": [
        s if s.strand_type.value != "staple" else s.model_copy(update={"id": s.id + suffix})
        for s in design.strands]})


def test_resize_is_recorded_by_position_and_verifies(part):
    http, headers = part
    design = state.get_or_404()
    staple = _low_staple_5p(design)
    dom = staple.domains[0]
    r = http.post("/api/design/strand-end-resize", headers=headers, json={"entries": [
        {"strand_id": staple.id, "helix_id": dom.helix_id, "end": "5p", "delta_bp": -1}]})
    assert r.status_code == 200, r.text
    entry = state.get_or_404().feature_log[-1]
    leaf = entry.children[-1] if getattr(entry, "children", None) else entry
    params = leaf.params
    assert params["_proof_version"] == 2
    assert "strand_id" not in params["entries"][0]
    assert params["entries"][0]["at"] == {"helix_id": dom.helix_id, "bp_index": dom.start_bp,
                                          "direction": dom.direction.value}
    report = assess_part_history(state.get_or_404(), execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report


def test_positional_resize_replays_onto_a_re_derived_strand(part):
    design = state.get_or_404()
    staple = _low_staple_5p(design)
    dom = staple.domains[0]
    v1 = {"entries": [{"strand_id": staple.id, "helix_id": dom.helix_id, "end": "5p", "delta_bp": -1}],
          "_proof_version": 1}
    v2 = to_positional("strand-end-resize", v1, design)
    renamed = _renamed(design, "-rerun")
    assert resolve("strand-end-resize", v2, renamed)["entries"][0]["strand_id"] == staple.id + "-rerun"
    expected = execute("strand-end-resize", design, v1)
    replayed = execute("strand-end-resize", renamed, v2)
    first = lambda d: next(s for s in d.strands if s.id.startswith(staple.id)).domains[0]  # noqa: E731
    assert (first(replayed).start_bp, first(replayed).end_bp) == (first(expected).start_bp, first(expected).end_bp)


def test_crossover_delete_resolves_by_its_halves(part):
    design = state.get_or_404()
    crossover = design.crossovers[0]
    v2 = to_positional("crossover-delete", {"crossover_id": crossover.id, "_proof_version": 1}, design)
    assert "crossover_id" not in v2 and v2["_proof_version"] == 2
    assert resolve("crossover-delete", v2, design)["crossover_id"] == crossover.id
    gone = design.model_copy(update={"crossovers": design.crossovers[1:]})
    with pytest.raises(PositionNotOccupied):
        resolve("crossover-delete", v2, gone)
    assert len(positions("crossover-delete", v2)) == 2


def test_v2_removal_rule_reads_positions():
    from backend.core.fine_routing_targets import no_longer_applies
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design([(0, 0)], length_bp=42)
    helix = design.helices[0].id
    direction = design.strands[0].domains[0].direction.value
    at = lambda bp: {"helix_id": helix, "bp_index": bp, "direction": direction}  # noqa: E731
    params = lambda bp: {"entries": [{"at": at(bp), "helix_id": helix, "end": "5p", "delta_bp": 1}],  # noqa: E731
                         "_proof_version": 2}
    assert not no_longer_applies("strand-end-resize", params(0), design)
    assert no_longer_applies("strand-end-resize", params(500), design)


def test_version_one_records_still_replay(part):
    design = state.get_or_404()
    staple = _low_staple_5p(design)
    dom = staple.domains[0]
    v1 = {"entries": [{"strand_id": staple.id, "helix_id": dom.helix_id, "end": "5p", "delta_bp": -1}],
          "_proof_version": 1}
    assert dependencies("strand-end-resize", v1).known
    assert dependencies("strand-end-resize", to_positional("strand-end-resize", v1, design)).known
    execute("strand-end-resize", design, v1)


def _routing_child(design, kind):
    for index, entry in enumerate(design.feature_log):
        if entry.feature_type == "routing-cluster":
            for sub, child in enumerate(entry.children):
                if child.op_subtype == kind:
                    return index, sub, entry, child
    raise AssertionError(kind)


def test_routing_step_editor_loads_and_edits_a_positional_child(part):
    """The feature-log routing editor edits v2 children by position over real HTTP."""
    http, headers = part
    design = state.get_or_404()
    staple = _low_staple_5p(design)
    dom = staple.domains[0]
    assert http.post("/api/design/strand-end-resize", headers=headers, json={"entries": [
        {"strand_id": staple.id, "helix_id": dom.helix_id, "end": "5p", "delta_bp": -1}]}).status_code == 200
    session_design = state.get_or_404()
    index, sub, parent, child = _routing_child(session_design, "strand-end-resize")
    _, revision = state.get_design_with_revision()
    guards = {"expected_design_id": session_design.id, "expected_revision": revision,
              "expected_feature_id": parent.id, "expected_child_id": child.id}
    packet = http.get(f"/api/design/features/{index}/routing-inputs", headers=headers,
                      params={"sub_index": sub, **guards})
    assert packet.status_code == 200, packet.text
    assert packet.json()["params"] == child.params and child.params["_proof_version"] == 2

    entries = [{**child.params["entries"][0], "delta_bp": -2}]
    r = http.post(f"/api/design/features/{index}/edit", headers=headers, params={"sub_index": sub},
                  json={"params": {"entries": entries}, **guards})
    assert r.status_code == 200, r.text
    edited = state.get_or_404()
    assert _routing_child(edited, "strand-end-resize")[3].params["entries"][0]["delta_bp"] == -2
    resized = next(s for s in edited.strands if s.id == staple.id)
    assert abs(resized.domains[0].start_bp - dom.start_bp) == 2  # the edited -2 bp, not the recorded -1
    assert assess_part_history(edited, execute=execute, dependencies=dependencies)["status"] == "verified"


def test_routing_step_editor_refuses_an_unoccupied_position(part):
    from backend.api.part_routing_edit_inputs import bind_prefix, normalize

    design = state.get_or_404()
    staple = _low_staple_5p(design)
    dom = staple.domains[0]
    v2 = to_positional("strand-end-resize", {"entries": [
        {"strand_id": staple.id, "helix_id": dom.helix_id, "end": "5p", "delta_bp": -1}], "_proof_version": 1}, design)
    moved = [{**v2["entries"][0], "at": {**v2["entries"][0]["at"], "bp_index": dom.start_bp + 5}}]
    with pytest.raises(PositionNotOccupied) as caught:
        bind_prefix("strand-end-resize", normalize("strand-end-resize", v2, {"entries": moved}), design)
    assert caught.value.references[0]["kind"] == "position"
    assert caught.value.references[0]["parameter_path"] == ["entries", 0, "at"]
