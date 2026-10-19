"""Region autostaple: restaple only the staples touching a selected region.

The region grows to every staple touching it; every other staple is kept
exactly (ids, domains, sequence) with its crossovers. The record stores the
region by position (helix + bp interval), so it replays after upstream edits.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api.part_proof_commands import dependencies, execute
from backend.core.occupancy import occupancy_conflicts
from backend.core.part_history_contract import assess_part_history


@pytest.fixture
def part():
    from backend.api.main import app

    identity = f"region-autostaple-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    http = TestClient(app)  # no lifespan
    assert http.post("/api/design", headers=headers, json={"name": "ra", "lattice_type": "HONEYCOMB"}).status_code == 201
    cells = [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
    assert http.post("/api/design/bundle", headers=headers, json={"cells": cells, "length_bp": 84, "name": "ra"}).status_code == 201
    assert http.post("/api/design/auto-scaffold-seamless", headers=headers, json={}).status_code == 200
    assert http.post("/api/design/full-autostaple", headers=headers, json={}).status_code == 200
    token = doc_context.set_current_doc(identity)
    try:
        yield http, headers
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        http.close()


def _staples(design):
    return {s.id: s for s in design.strands if s.strand_type.value == "staple" and not s.is_reference}


def _covered(design):
    return {(d.helix_id, bp, d.direction.value) for s in _staples(design).values() for d in s.domains
            for bp in range(min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp) + 1)}


def _region(design, helix_index=0, lo=0, hi=20):
    return [{"helix_id": design.helices[helix_index].id, "lo_bp": lo, "hi_bp": hi}]


def _touching(design, region):
    from backend.api.part_autostaple_command import region_staple_ids
    from backend.api.routes_assign_sequences import _RegionInterval

    return region_staple_ids(design, [_RegionInterval(**item) for item in region])


def test_region_autostaple_keeps_every_other_staple_exactly(part):
    http, headers = part
    before = state.get_or_404()
    region = _region(before)
    inside = _touching(before, region)
    assert inside and len(inside) < len(_staples(before))
    r = http.post("/api/design/full-autostaple", headers=headers, json={"region": region})
    assert r.status_code == 200, r.text
    assert r.json()["full_autostaple"]["region"]["restapled"] == len(inside)
    after = state.get_or_404()
    kept = {sid: s for sid, s in _staples(before).items() if sid not in inside}
    for sid, strand in kept.items():
        assert _staples(after)[sid] == strand
    assert _covered(after) == _covered(before)
    assert not occupancy_conflicts(after)[0]
    entry = after.feature_log[-1]
    assert entry.op_kind == "full-autostaple" and entry.label == "Region autostaple"
    assert entry.params["region"] == region
    assert assess_part_history(after, execute=execute, dependencies=dependencies)["status"] == "verified"


def test_hand_edit_outside_the_region_survives_but_inside_is_restapled(part):
    http, headers = part
    design = state.get_or_404()
    region = _region(design, 0, 0, 20)
    inside = _touching(design, region)

    def nick_on(strands):
        strand = next(s for s in strands if len(s.domains) >= 2)
        d = max(strand.domains, key=lambda dom: abs(dom.end_bp - dom.start_bp))
        bp = (d.start_bp + d.end_bp) // 2
        return {"helix_id": d.helix_id, "bp_index": bp, "direction": d.direction.value}

    staples = _staples(design)
    outside_nick = nick_on([s for sid, s in staples.items() if sid not in inside])
    # Nick inside the region interval itself, so both fragments still touch it.
    helix = region[0]["helix_id"]
    dom = next(d for s in staples.values() for d in s.domains
               if d.helix_id == helix and min(d.start_bp, d.end_bp) < 10 < max(d.start_bp, d.end_bp))
    inside_nick = {"helix_id": helix, "bp_index": 10, "direction": dom.direction.value}
    for nick in (outside_nick, inside_nick):
        assert http.post("/api/design/nick", headers=headers, json=nick).status_code in (200, 201)
    nicked = state.get_or_404()
    assert len(_staples(nicked)) == len(staples) + 2

    assert http.post("/api/design/full-autostaple", headers=headers, json={"region": region}).status_code == 200
    after = state.get_or_404()
    region_after = _touching(nicked, region)
    for sid, strand in _staples(nicked).items():
        if sid not in region_after:
            assert _staples(after)[sid] == strand  # includes both outside-nick fragments
    assert len(_staples(after)) == len(staples) + 1  # only the inside nick was healed
    assert not occupancy_conflicts(after)[0]


def test_region_autostaple_replays_after_an_upstream_length_edit(part):
    http, headers = part
    region = _region(state.get_or_404(), 1, 0, 30)
    assert http.post("/api/design/full-autostaple", headers=headers, json={"region": region}).status_code == 200
    r = http.post("/api/design/features/0/edit", headers=headers, json={"params": {"length_bp": 63}})
    assert r.status_code == 200, r.text
    after = state.get_or_404()
    assert after.feature_log[-1].params["region"] == region
    assert not occupancy_conflicts(after)[0]
    assert assess_part_history(after, execute=execute, dependencies=dependencies)["status"] == "verified"


def test_whole_structure_record_is_unchanged_and_idempotent(part):
    http, headers = part
    before = state.get_or_404()
    row = next(e for e in before.feature_log if getattr(e, "op_kind", None) == "full-autostaple")
    assert "region" not in row.params
    assert http.post("/api/design/full-autostaple", headers=headers, json={}).status_code == 200
    assert _covered(state.get_or_404()) == _covered(before)


@pytest.mark.parametrize("region, message", [
    ([], "Select a region"),
    ([{"helix_id": "missing", "lo_bp": 0, "hi_bp": 4}], "not found"),
    (None, "No staples touch"),
])
def test_invalid_regions_refuse_without_changing_the_part(part, region, message):
    http, headers = part
    before, revision = state.get_design_with_revision()
    if region is None:
        region = [{"helix_id": before.helices[0].id, "lo_bp": 5000, "hi_bp": 5001}]
    r = http.post("/api/design/full-autostaple", headers=headers, json={"region": region})
    assert r.status_code == 422 and message in r.text
    assert state.get_design_with_revision() == (before, revision)


def test_region_restaple_of_an_autostapled_part_is_idempotent_for_every_helix(part):
    """Autostaple is idempotent; restricting it to any region must preserve that."""
    http, headers = part

    def topology(design):
        staples = sorted(tuple((d.helix_id, d.start_bp, d.end_bp, d.direction.value) for d in s.domains)
                         for s in _staples(design).values())
        crossovers = sorted(tuple(sorted((h.helix_id, h.index, h.strand.value) for h in (x.half_a, x.half_b)))
                            for x in design.crossovers)
        return staples, crossovers

    base = state.get_or_404()
    expected = topology(base)
    for helix in base.helices:
        state.load_design(base)
        r = http.post("/api/design/full-autostaple", headers=headers,
                      json={"region": [{"helix_id": helix.id, "lo_bp": 30, "hi_bp": 50}]})
        assert r.status_code == 200, r.text
        assert topology(state.get_or_404()) == expected, helix.id


def test_kept_staples_keep_typed_sequences_and_regain_cleared_ones(part):
    http, headers = part
    design = state.get_or_404()
    region = _region(design, 0, 0, 20)
    inside = _touching(design, region)
    outside = [s for sid, s in _staples(design).items() if sid not in inside]
    typed, cleared = outside[0], outside[1]
    custom = "T" * len(typed.sequence)
    patched = design.copy_with(strands=[
        s.model_copy(update={"sequence": custom}) if s.id == typed.id
        else s.model_copy(update={"sequence": None}) if s.id == cleared.id else s
        for s in design.strands])
    state.load_design(patched)
    assert http.post("/api/design/full-autostaple", headers=headers, json={"region": region}).status_code == 200
    after = _staples(state.get_or_404())
    assert after[typed.id].sequence == custom
    assert after[cleared.id].sequence == cleared.sequence  # re-derived from the scaffold
    assert after[cleared.id].domains == cleared.domains
