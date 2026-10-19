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


def test_existing_violation_may_be_edited_but_not_worsened(document):
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
    # An unrelated edit still works on the already-violating part...
    other = next(h for h in design.helices if h.id != domain.helix_id)
    assert http.post("/api/design/nick", headers=headers, json={
        "helix_id": other.id, "bp_index": 20, "direction": "FORWARD"}).status_code in {200, 201}
    # ...but adding another conflicting slot is refused.
    worse = http.post("/api/design/strands", headers=headers, json=_overlapping_strand_body(state.get_or_404()))
    assert worse.status_code == 409
