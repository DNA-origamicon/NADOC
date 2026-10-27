"""Every (helix, bp, direction) slot holds at most one base of one strand (ISSUE-19 invariant)."""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.core.lattice import make_bundle_design
from backend.core.models import Direction, Domain, Strand, StrandType
from backend.core.occupancy import occupancy_conflicts
from backend.core.validator import validate_design


def _strand(sid, helix_id, lo, hi, direction, strand_type=StrandType.STAPLE, *, reference=False):
    start, end = (lo, hi) if direction == Direction.FORWARD else (hi, lo)
    return Strand(id=sid, strand_type=strand_type, is_reference=reference,
                  domains=[Domain(helix_id=helix_id, start_bp=start, end_bp=end, direction=direction)])


def test_clean_bundle_has_no_conflicts_and_validates():
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    assert occupancy_conflicts(design) == ([], 0)
    assert any(r.ok and "at most one base" in r.message for r in validate_design(design).results)


def test_overlap_same_direction_is_counted_exactly():
    design = make_bundle_design([(0, 0)], length_bp=42)
    helix = design.helices[0].id
    design = design.copy_with(strands=[_strand("a", helix, 0, 20, Direction.FORWARD),
                                       _strand("b", helix, 15, 30, Direction.FORWARD)])
    conflicts, total = occupancy_conflicts(design)
    assert total == 6  # bp 15..20
    assert conflicts == [{"helix_id": helix, "bp": 15, "bp_end": 20, "direction": "FORWARD", "strand_ids": ["a", "b"]}]
    report = validate_design(design)
    assert not report.passed and any("more than one base" in r.message for r in report.results)


def test_opposite_directions_and_reference_strands_do_not_conflict():
    design = make_bundle_design([(0, 0)], length_bp=42)
    helix = design.helices[0].id
    design = design.copy_with(strands=[
        _strand("fwd", helix, 0, 30, Direction.FORWARD),
        _strand("rev", helix, 0, 30, Direction.REVERSE),
        _strand("ref", helix, 0, 30, Direction.FORWARD, reference=True),
    ])
    assert occupancy_conflicts(design)[1] == 0


def test_a_strand_covering_its_own_slot_twice_conflicts():
    design = make_bundle_design([(0, 0)], length_bp=42)
    helix = design.helices[0].id
    twice = Strand(id="loop", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id=helix, start_bp=0, end_bp=10, direction=Direction.FORWARD),
        Domain(helix_id=helix, start_bp=5, end_bp=12, direction=Direction.FORWARD)])
    assert occupancy_conflicts(design.copy_with(strands=[twice]))[1] == 6


@pytest.fixture
def document():
    from backend.api.main import app

    identity = f"occupancy-{uuid4()}"
    http = TestClient(app)  # no lifespan
    token = doc_context.set_current_doc(identity)
    try:
        yield http, {"X-NADOC-Doc": identity}
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        http.close()


def _overlapping_strand_body(design):
    scaffold = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    domain = scaffold.domains[0]
    return {"strand_type": "staple", "domains": [{
        "helix_id": domain.helix_id, "start_bp": domain.start_bp, "end_bp": domain.end_bp,
        "direction": domain.direction.value}]}


def test_mutation_adding_a_double_occupancy_is_refused_and_rolled_back(document):
    http, headers = document
    assert http.post("/api/design", headers=headers, json={"name": "occ", "lattice_type": "HONEYCOMB"}).status_code == 201
    assert http.post("/api/design/bundle", headers=headers, json={"cells": [[0, 0], [0, 1]], "length_bp": 42, "name": "occ"}).status_code == 201
    before, revision = state.get_design_with_revision()
    snapshot = before.model_dump(mode="json")
    response = http.post("/api/design/strands", headers=headers, json=_overlapping_strand_body(before))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "nucleotide_double_occupancy"
    after, after_revision = state.get_design_with_revision()
    assert after.model_dump(mode="json") == snapshot and after_revision == revision


def test_existing_violation_requires_completely_collision_free_edit(document):
    http, headers = document
    assert http.post("/api/design", headers=headers, json={"name": "occ", "lattice_type": "HONEYCOMB"}).status_code == 201
    assert http.post("/api/design/bundle", headers=headers, json={"cells": [[0, 0], [0, 1]], "length_bp": 42, "name": "occ"}).status_code == 201
    design = state.get_or_404()
    scaffold = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    domain = scaffold.domains[0]
    lo, hi = sorted((domain.start_bp, domain.end_bp))
    bad = _strand("old-import-overlap", domain.helix_id, lo, lo + 4, domain.direction)
    state.load_design(design.copy_with(strands=[*design.strands, bad]))  # e.g. an old import
    assert occupancy_conflicts(state.get_or_404())[1] == 5
    before, revision = state.get_design_with_revision()
    snapshot = before.model_dump_json()
    # Even an unrelated edit must leave a completely collision-free result.
    other = next(h for h in design.helices if h.id != domain.helix_id)
    assert http.post("/api/design/nick", headers=headers, json={
        "helix_id": other.id, "bp_index": 20, "direction": "FORWARD"}).status_code == 409
    after, after_revision = state.get_design_with_revision()
    assert after.model_dump_json() == snapshot and after_revision == revision
    # ...but adding another conflicting slot is refused.
    worse = http.post("/api/design/strands", headers=headers, json=_overlapping_strand_body(state.get_or_404()))
    assert worse.status_code == 409
    repaired = http.delete('/api/design/strands/old-import-overlap', headers=headers)
    assert repaired.status_code == 200
    assert occupancy_conflicts(state.get_or_404()) == ([], 0)
    # Undo must not reintroduce the invalid imported topology or consume history.
    from fastapi import HTTPException
    fixed, fixed_revision = state.get_design_with_revision()
    fixed_snapshot = fixed.model_dump_json()
    history_depth, redo_depth = state.undo_depth(), state.redo_depth()
    with pytest.raises(HTTPException) as error:
        state.undo()
    assert error.value.detail['code'] == 'nucleotide_double_occupancy'
    after, after_revision = state.get_design_with_revision()
    assert after.model_dump_json() == fixed_snapshot and after_revision == fixed_revision
    assert (state.undo_depth(), state.redo_depth()) == (history_depth, redo_depth)


def test_three_claimants_count_each_slot_once_and_report_all_owners():
    design = make_bundle_design([(0, 0)], length_bp=42)
    helix = design.helices[0].id
    design = design.copy_with(strands=[_strand(sid, helix, 3, 8, Direction.FORWARD)
                                       for sid in ('a', 'b', 'c')])
    conflicts, total = occupancy_conflicts(design)
    assert total == 6
    assert conflicts[0]['strand_ids'] == ['a', 'b', 'c']
    assert occupancy_conflicts(design, limit=0) == ([], 6)


def test_interval_occupancy_matches_explicit_slot_map():
    from collections import Counter
    from random import Random

    rng = Random(126)
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    strands, expected = [], Counter()
    for index in range(40):
        helix = rng.choice(design.helices).id
        direction = rng.choice([Direction.FORWARD, Direction.REVERSE])
        lo = rng.randrange(-5, 35)
        hi = lo + rng.randrange(1, 10)
        reference = index % 7 == 0
        strands.append(_strand(str(index), helix, lo, hi, direction, reference=reference))
        if not reference:
            expected.update((helix, bp, direction.value) for bp in range(lo, hi + 1))
    conflicts, total = occupancy_conflicts(design.copy_with(strands=strands), limit=1000)
    actual = {(c['helix_id'], bp, c['direction']) for c in conflicts
              for bp in range(c['bp'], c['bp_end'] + 1)}
    assert actual == {slot for slot, count in expected.items() if count > 1}
    assert total == len(actual)


@pytest.mark.parametrize('executor_name', ['execute', 'execute_long'])
def test_native_execution_never_accepts_conflicting_output(monkeypatch, executor_name):
    from backend.api import part_proof_commands
    from backend.core.part_command_errors import CommandContractError

    source = make_bundle_design([(0, 0)], length_bp=42)
    snapshot = source.model_dump_json()
    domain = source.strands[0].domains[0]
    duplicate = _strand('conflicting-output', domain.helix_id, 0, 4, domain.direction)
    candidate = source.copy_with(strands=[*source.strands, duplicate])
    monkeypatch.setattr(part_proof_commands, '_execute_candidate', lambda *a, **kw: candidate)
    with pytest.raises(CommandContractError) as error:
        getattr(part_proof_commands, executor_name)('test-native-command', source, {})
    assert error.value.code == 'nucleotide_double_occupancy'
    assert domain.helix_id in str(error.value) and 'conflicting-output' in str(error.value)
    assert source.model_dump_json() == snapshot


def test_partial_repair_refuses_but_atomic_complete_repair_succeeds(document):
    http, headers = document
    design = make_bundle_design([(0, 0)], length_bp=42)
    domain = design.strands[0].domains[0]
    conflicts = [_strand(sid, domain.helix_id, lo, lo + 2, domain.direction)
                 for sid, lo in [('conflict-a', 3), ('conflict-b', 12)]]
    state.load_design(design.copy_with(strands=[*design.strands, *conflicts]))
    before, revision = state.get_design_with_revision()
    snapshot = before.model_dump_json()
    response = http.delete('/api/design/strands/conflict-a', headers=headers)
    assert response.status_code == 409
    after, after_revision = state.get_design_with_revision()
    assert after.model_dump_json() == snapshot and after_revision == revision
    assert state.undo_depth() == state.redo_depth() == 0
    response = http.request('DELETE', '/api/design/strands/batch', headers=headers,
                            json={'strand_ids': ['conflict-a', 'conflict-b']})
    assert response.status_code == 200
    assert occupancy_conflicts(state.get_or_404()) == ([], 0)
    assert state.undo_depth() == 1


def test_redo_refuses_conflicting_snapshot_without_consuming_stacks(document):
    from fastapi import HTTPException

    design = make_bundle_design([(0, 0)], length_bp=42)
    domain = design.strands[0].domains[0]
    bad = design.copy_with(strands=[*design.strands,
        _strand('invalid-redo', domain.helix_id, 3, 5, domain.direction)])
    state.load_design(design)
    session = state._session()
    session.redo.append(bad)  # A persisted pre-invariant history entry.
    revision = session.revision
    with pytest.raises(HTTPException) as error:
        state.redo()
    assert error.value.detail['code'] == 'nucleotide_double_occupancy'
    assert session.design is design and session.revision == revision
    assert not session.history and list(session.redo) == [bad]
