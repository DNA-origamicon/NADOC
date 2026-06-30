"""Auto-assign on connect/set: connecting overhangs (linker / end-to-root) or
setting an overhang sequence propagates REAL reverse-complement bases to the
linker-complement / binder strands when the scaffold is already sequenced — so
the result is simulation-ready without a manual 'Assign Staple Sequences'.

Guard: a no-op when the scaffold is unsequenced (nothing to pair against).
See backend/core/sequences.py::reassign_if_sequenced.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    ConnectionVersion, Direction, Domain, Helix, OverhangSpec, Strand,
    StrandType, Vec3,
)

client = TestClient(app)


def _seed(*, scaffold_sequenced: bool, seq_a="ACGTACGT", seq_b="TTTTGGGG"):
    """Two extruded overhangs (own helix/strand) carrying sequences + a scaffold
    strand (optionally sequenced, so the auto-assign guard fires or no-ops)."""
    def _oh(hid, sid, oid, x, seq):
        h = Helix(id=hid, axis_start=Vec3(x=x, y=0, z=0),
                  axis_end=Vec3(x=x, y=0, z=8 * BDNA_RISE_PER_BP),
                  phase_offset=0.0, length_bp=8, grid_pos=(0, int(x)))
        s = Strand(id=sid, strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id=hid, start_bp=0, end_bp=7, direction=Direction.FORWARD,
                   overhang_id=oid)])
        spec = OverhangSpec(id=oid, helix_id=hid, strand_id=sid, label=oid.upper(),
                            sequence=seq)            # ctor-time seq → whole sub-domain sized to len
        return h, s, spec

    ha, sa, oa = _oh("oh_helix_a", "oh_strand_a", "oh_a", 2, seq_a)
    hb, sb, ob = _oh("oh_helix_b", "oh_strand_b", "oh_b", 5, seq_b)
    scaf_h = Helix(id="scaf_h", axis_start=Vec3(x=10, y=0, z=0),
                   axis_end=Vec3(x=10, y=0, z=8 * BDNA_RISE_PER_BP),
                   phase_offset=0.0, length_bp=8, grid_pos=(1, 0))
    scaf = Strand(id="scaf", strand_type=StrandType.SCAFFOLD,
                  domains=[Domain(helix_id="scaf_h", start_bp=0, end_bp=7,
                                  direction=Direction.FORWARD)],
                  sequence=("AAAACCCC" if scaffold_sequenced else None))
    return _demo_design().model_copy(update={
        "helices": [ha, hb, scaf_h], "strands": [sa, sb, scaf],
        "overhangs": [oa, ob],
    })


def _strand_seq(design, predicate):
    return next((s.sequence for s in design.strands if predicate(s)), None)


def test_connect_linker_propagates_real_complement_when_scaffold_sequenced():
    """Creating a ds linker between two sequenced overhangs fills each linker
    complement domain with the overhang's reverse complement (real bases) — no
    manual assign needed."""
    design_state.close_session(); design_state.set_design(_seed(scaffold_sequenced=True))
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b", "overhang_b_attach": "root",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp"})
    assert r.status_code in (200, 201), r.text
    d = design_state.get_or_404()
    comp_a = _strand_seq(d, lambda s: s.id.endswith("__a") and "__lnk__" in s.id)
    assert comp_a is not None
    # The complement of overhang A (ACGTACGT, antiparallel) starts the strand;
    # it must be REAL (contain assigned bases), not all-N.
    assert "ACGTACGT" in comp_a, comp_a
    assert comp_a.count("N") < len(comp_a)          # not fully unassigned


def test_connect_linker_noop_when_scaffold_unsequenced():
    """Guard: with no scaffold sequence there is nothing to pair against, so the
    complement stays unassigned (the auto-assign no-ops rather than raising)."""
    design_state.close_session(); design_state.set_design(_seed(scaffold_sequenced=False))
    r = client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b", "overhang_b_attach": "root",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp"})
    assert r.status_code in (200, 201), r.text
    d = design_state.get_or_404()
    comp_a = _strand_seq(d, lambda s: s.id.endswith("__a") and "__lnk__" in s.id)
    assert comp_a is None                            # unassigned (real bases come later)


def test_patch_overhang_sequence_reassigns_complement():
    """Setting an overhang's sequence after a linker exists re-derives the
    complement to the new RC (auto-assign on set)."""
    design_state.close_session(); design_state.set_design(_seed(scaffold_sequenced=True, seq_a="AAAAAAAA"))
    client.post("/api/design/overhang-connections", json={
        "overhang_a_id": "oh_a", "overhang_a_attach": "free_end",
        "overhang_b_id": "oh_b", "overhang_b_attach": "root",
        "linker_type": "ds", "length_value": 6, "length_unit": "bp"})
    # Now change A's sequence → complement must follow (TTTTTTTT region).
    r = client.patch("/api/design/overhang/oh_a", json={"sequence": "GGGGGGGG"})
    assert r.status_code == 200, r.text
    d = design_state.get_or_404()
    comp_a = _strand_seq(d, lambda s: s.id.endswith("__a") and "__lnk__" in s.id)
    assert comp_a is not None and "CCCCCCCC" in comp_a, comp_a   # RC of GGGG…
