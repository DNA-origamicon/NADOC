"""Regression: POST /design/assign-staple-sequences must NOT clear or reassign
user-specified overhang sequences.

An earlier version of ``assign_staple_sequences_endpoint`` wiped every
``OverhangSpec.sequence`` to ``None`` before assigning, so re-running "Assign
Staple Sequences" destroyed toehold/handle sequences the user had entered. The
core ``assign_staple_sequences`` already reads each overhang's stored sequence
(via ``_assemble_overhang_5to3``) and threads it into the containing staple, so
the clearing was removed. This pins that overhang sequences survive the endpoint.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import LatticeType

client = TestClient(app)

SIX_HB_CELLS = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]


def _routed_scaffolded_with_overhang():
    """Build a routed, scaffold-sequenced 6hb with one extruded overhang on the
    DEFAULT doc (the routes read it). Returns the overhang id."""
    from tests.test_headless_build import _place_one_overhang

    hb.new_design(LatticeType.HONEYCOMB)
    hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
    hb.auto_scaffold(seamless=False)
    hb.auto_crossover()
    hb.auto_break()
    hb.assign_scaffold_sequence()
    d = _place_one_overhang(design_state.get_or_404())
    assert d is not None and len(d.overhangs) == 1
    design_state.set_design(d)
    return d.overhangs[0].id


def test_assign_staple_sequences_preserves_overhang_sequence():
    ovhg_id = _routed_scaffolded_with_overhang()

    # User sets an overhang (handle/toehold) sequence.
    my_seq = "ACGTACGT"
    r = client.patch(f"/api/design/overhang/{ovhg_id}", json={"sequence": my_seq})
    assert r.status_code == 200, r.text
    before = {o["id"]: o.get("sequence") for o in r.json()["design"]["overhangs"]}
    assert before[ovhg_id] == my_seq

    # Re-run Assign Staple Sequences: the overhang sequence must survive.
    r2 = client.post("/api/design/assign-staple-sequences")
    assert r2.status_code == 200, r2.text
    after = {o["id"]: o.get("sequence") for o in r2.json()["design"]["overhangs"]}
    assert after[ovhg_id] == my_seq, (
        f"overhang sequence was cleared/reassigned by assign-staple-sequences: "
        f"{after[ovhg_id]!r} != {my_seq!r}"
    )

    # And the containing staple strand carries those overhang bases.
    design = design_state.get_or_404()
    ovhg = next(o for o in design.overhangs if o.id == ovhg_id)
    staple = next(s for s in design.strands if s.id == ovhg.strand_id)
    assert staple.sequence is not None
    assert my_seq in staple.sequence
