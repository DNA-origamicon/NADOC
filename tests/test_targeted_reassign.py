"""The implicit auto-assign hooks must be TARGETED, not design-wide.

Patching an overhang, creating an overhang connection, or applying a connection
version only ever changes a handful of strands — the overhang's own strand, its
binders/linker complements, and the new ``__lnk__`` bridge strands.  They used to
call ``reassign_if_sequenced``, which re-derives EVERY non-scaffold strand in the
design, silently destroying any sequence the user had typed by hand elsewhere.

They now call ``reassign_strands`` over ``overhang_dependent_strand_ids``.  These
tests pin both halves of the contract:
  * an unrelated hand-typed staple sequence SURVIVES all three hooks, and
  * the linker complement / binder still gets REAL reverse-complement bases
    (the pre-existing guarantee from project_overhang_sequence_display §3).

The EXPLICIT bulk commands are the opposite: "Assign staple sequences" and
"Full autostaple" are *supposed* to overwrite a manual sequence, and both push an
undo snapshot so it can be brought back.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3,
)

client = TestClient(app)

# A hand-typed sequence that is deliberately NOT the scaffold complement, so any
# re-derivation of this strand is immediately visible.
MANUAL_SEQ = "ACGTACGT"
# What the derivation WOULD produce for `unrelated` (scaffold AAAACCCC on scaf_h
# FORWARD; the staple runs REVERSE 7→0, so each base is the complement of the
# scaffold base at the same bp, read high→low).
DERIVED_SEQ = "GGGGTTTT"


def _seed(*, scaffold_sequenced: bool = True, seq_a="ACGTACGT", seq_b="TTTTGGGG"):
    """Two extruded overhangs + a sequenced scaffold + one UNRELATED staple.

    The unrelated staple pairs with the scaffold but touches neither overhang, so
    no targeted hook has any reason to re-derive it.
    """
    def _oh(hid, sid, oid, x, seq):
        h = Helix(id=hid, axis_start=Vec3(x=x, y=0, z=0),
                  axis_end=Vec3(x=x, y=0, z=8 * BDNA_RISE_PER_BP),
                  phase_offset=0.0, length_bp=8, grid_pos=(0, int(x)))
        s = Strand(id=sid, strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id=hid, start_bp=0, end_bp=7, direction=Direction.FORWARD,
                   overhang_id=oid)])
        spec = OverhangSpec(id=oid, helix_id=hid, strand_id=sid, label=oid.upper(),
                            sequence=seq)
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
    unrelated = Strand(id="unrelated", strand_type=StrandType.STAPLE,
                       domains=[Domain(helix_id="scaf_h", start_bp=7, end_bp=0,
                                       direction=Direction.REVERSE)],
                       sequence=MANUAL_SEQ)
    return _demo_design().model_copy(update={
        "helices": [ha, hb, scaf_h], "strands": [sa, sb, scaf, unrelated],
        "overhangs": [oa, ob],
    })


def _seq(strand_id: str) -> str | None:
    d = design_state.get_or_404()
    return next((s.sequence for s in d.strands if s.id == strand_id), None)


def _linker_complement() -> str | None:
    d = design_state.get_or_404()
    return next((s.sequence for s in d.strands
                 if s.id.endswith("__a") and "__lnk__" in s.id), None)


def _connect(**kw):
    body = {"overhang_a_id": "oh_a", "overhang_a_attach": "free_end",
            "overhang_b_id": "oh_b", "overhang_b_attach": "root",
            "linker_type": "ds", "length_value": 6, "length_unit": "bp"}
    body.update(kw)
    return client.post("/api/design/overhang-connections", json=body)


# ── The derivation oracle itself ──────────────────────────────────────────────


def test_derived_sequence_oracle_is_what_we_think_it_is():
    """Pin DERIVED_SEQ: a design-wide re-derive really does rewrite `unrelated`
    to GGGGTTTT. Without this, the survival tests below could pass vacuously."""
    from backend.core.sequences import assign_staple_sequences
    design_state.close_session(); design_state.set_design(_seed())
    rederived = assign_staple_sequences(design_state.get_or_404())
    got = next(s.sequence for s in rederived.strands if s.id == "unrelated")
    assert got == DERIVED_SEQ
    assert got != MANUAL_SEQ


# ── The three implicit hooks leave unrelated strands alone ────────────────────


def test_patch_overhang_does_not_touch_unrelated_strand():
    design_state.close_session(); design_state.set_design(_seed())
    r = client.patch("/api/design/overhang/oh_a", json={"sequence": "GGGGGGGG"})
    assert r.status_code == 200, r.text
    assert _seq("unrelated") == MANUAL_SEQ


def test_patch_overhang_still_updates_its_own_strand():
    """The narrowing must not break the auto-assign it exists for."""
    design_state.close_session(); design_state.set_design(_seed())
    r = client.patch("/api/design/overhang/oh_a", json={"sequence": "GGGGGGGG"})
    assert r.status_code == 200, r.text
    assert _seq("oh_strand_a") == "GGGGGGGG"


def test_create_connection_does_not_touch_unrelated_strand():
    design_state.close_session(); design_state.set_design(_seed())
    r = _connect()
    assert r.status_code in (200, 201), r.text
    assert _seq("unrelated") == MANUAL_SEQ


def test_create_connection_still_propagates_real_complement():
    """Regression guard for project_overhang_sequence_display §3 — the linker
    complement must carry REAL reverse-complement bases, not poly-N."""
    design_state.close_session(); design_state.set_design(_seed())
    assert _connect().status_code in (200, 201)
    comp = _linker_complement()
    assert comp is not None
    assert "ACGTACGT" in comp, comp          # RC of overhang A (ACGTACGT)
    assert comp.count("N") < len(comp)


def test_patch_overhang_after_connect_still_re_derives_complement():
    design_state.close_session()
    design_state.set_design(_seed(seq_a="AAAAAAAA"))
    assert _connect().status_code in (200, 201)
    r = client.patch("/api/design/overhang/oh_a", json={"sequence": "GGGGGGGG"})
    assert r.status_code == 200, r.text
    comp = _linker_complement()
    assert comp is not None and "CCCCCCCC" in comp, comp
    assert _seq("unrelated") == MANUAL_SEQ


def test_apply_connection_version_does_not_touch_unrelated_strand():
    design_state.close_session(); design_state.set_design(_seed())
    r = client.post("/api/design/connection-versions", json={
        "overhang_a_id": "oh_a", "overhang_b_id": "oh_b",
        "connection_type": "ds_linker",
        "overhang_a_seq": "GGGGGGGG", "overhang_b_seq": "CCCCCCCC",
        "bridge_length": 6, "bridge_seq": "TTTTTT"})
    assert r.status_code in (200, 201), r.text
    vid = r.json()["design"]["connection_versions"][0]["id"]
    r = client.post(f"/api/design/connection-versions/{vid}/apply")
    assert r.status_code == 200, r.text
    assert _seq("unrelated") == MANUAL_SEQ
    # …and the version really was materialized (not a vacuous pass).
    assert _seq("oh_strand_a") == "GGGGGGGG"


# ── The explicit bulk commands DO override, and undo brings it back ───────────


def test_assign_staple_sequences_overrides_manual_sequence():
    design_state.close_session(); design_state.set_design(_seed())
    r = client.post("/api/design/assign-staple-sequences")
    assert r.status_code == 200, r.text
    assert _seq("unrelated") == DERIVED_SEQ


def test_undo_restores_a_manual_sequence_after_bulk_assign():
    design_state.close_session(); design_state.set_design(_seed())
    assert client.post("/api/design/assign-staple-sequences").status_code == 200
    assert _seq("unrelated") == DERIVED_SEQ
    assert client.post("/api/design/undo").status_code == 200
    assert _seq("unrelated") == MANUAL_SEQ
