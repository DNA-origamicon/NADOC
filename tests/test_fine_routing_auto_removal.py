"""Edits that leave a fine-routing feature with no strand remove that feature (cadnano-style).

Guardrails: only Fine Routing children whose every target is unoccupied/gone;
reported on the response; one undo restores the edit and the removed feature;
any other downstream failure still refuses and names the feature.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history


@pytest.fixture
def part():
    from backend.api.main import app

    identity = f"fine-routing-removal-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    http = TestClient(app)  # no lifespan
    assert http.post("/api/design", headers=headers, json={"name": "fr", "lattice_type": "HONEYCOMB"}).status_code == 201
    cells = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
    assert http.post("/api/design/bundle", headers=headers, json={"cells": cells, "length_bp": 84, "name": "fr"}).status_code == 201
    assert http.post("/api/design/auto-scaffold-seamless", headers=headers, json={}).status_code == 200
    assert http.post("/api/design/full-autostaple", headers=headers, json={}).status_code == 200
    token = doc_context.set_current_doc(identity)
    try:
        yield http, headers
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        http.close()


def _nick_on_staple(http, headers, *, high):
    design = state.get_or_404()

    def reach(strand):
        return max(max(d.start_bp, d.end_bp) for d in strand.domains)

    staples = [s for s in design.strands if s.strand_type.value == "staple" and len(s.domains) >= 2]
    staple = next(s for s in staples if reach(s) > 70) if high else min(staples, key=reach)
    dom = max(staple.domains, key=lambda d: max(d.start_bp, d.end_bp)) if high else staple.domains[0]
    lo, hi = sorted((dom.start_bp, dom.end_bp))
    bp = hi - 2 if high else (lo + hi) // 2
    r = http.post("/api/design/nick", headers=headers,
                  json={"helix_id": dom.helix_id, "bp_index": bp, "direction": dom.direction.value})
    assert r.status_code in (200, 201), r.text
    return dom.helix_id, bp


def _verified():
    return assess_part_history(state.get_or_404(), execute=execute, dependencies=dependencies)["status"]


def test_shortening_the_extrude_under_a_nick_removes_the_nick(part):
    http, headers = part
    helix_id, bp = _nick_on_staple(http, headers, high=True)
    assert bp >= 63
    before = state.get_or_404().model_dump(mode="json")
    assert any(e.feature_type == "routing-cluster" for e in state.get_or_404().feature_log)

    r = http.post("/api/design/features/0/edit", headers=headers, json={"params": {"length_bp": 63}})
    assert r.status_code == 200, r.text
    removed = r.json()["removed_features"]
    assert [item["kind"] for item in removed] == ["nick"]
    assert any("no longer occupied" in w for w in r.json()["placement_warnings"])
    after = state.get_or_404()
    assert not any(e.feature_type == "routing-cluster" for e in after.feature_log)
    assert _verified() == "verified"

    assert http.post("/api/design/undo", headers=headers).status_code == 200
    assert state.get_or_404().model_dump(mode="json") == before  # one undo restores both


def test_a_nick_that_still_lands_on_a_strand_survives(part):
    http, headers = part
    helix_id, bp = _nick_on_staple(http, headers, high=False)
    assert bp < 63
    r = http.post("/api/design/features/0/edit", headers=headers, json={"params": {"length_bp": 63}})
    assert r.status_code == 200, r.text
    assert "removed_features" not in r.json()
    assert any(e.feature_type == "routing-cluster" for e in state.get_or_404().feature_log)
    assert _verified() == "verified"


def test_non_fine_routing_failures_still_refuse():
    """A downstream tool feature (fixed-endpoint bend) that cannot regenerate is
    never auto-removed: the edit is refused and the feature named (C4)."""
    from fastapi import HTTPException
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    from tests.deformation_history_app import fixture

    source = fixture("bend-fixed")
    index = [row.id for row in source.feature_log].index("edited-feature")
    with pytest.raises(HTTPException) as caught:
        prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None,
                       params={"type": "bend", "plane_a_bp": 4, "plane_b_bp": 32,
                               "params": {"kind": "bend", "curvature_deg_per_bp": .6, "direction_deg": 0}})
    assert caught.value.status_code == 409 and caught.value.detail["feature_id"] == "fixed-feature"


def test_removal_rule_decides_from_targets_only():
    from backend.core.fine_routing_targets import no_longer_applies
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design([(0, 0)], length_bp=42)
    helix = design.helices[0].id
    direction = design.strands[0].domains[0].direction.value
    assert not no_longer_applies("nick", {"helix_id": helix, "bp_index": 10, "direction": direction}, design)
    assert no_longer_applies("nick", {"helix_id": helix, "bp_index": 500, "direction": direction}, design)
    assert not no_longer_applies("nick-batch", {"nicks": [
        {"helix_id": helix, "bp_index": 500, "direction": direction},
        {"helix_id": helix, "bp_index": 10, "direction": direction}]}, design)  # partially applicable
    assert no_longer_applies("crossover-delete", {"crossover_id": "gone"}, design)
    assert not no_longer_applies("auto-break", {}, design)  # not a fine-routing target kind
