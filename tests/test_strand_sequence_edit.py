"""Hand-editing a strand's sequence: PATCH /design/strand/{id} + the read side
GET /design/strand/{id}/sequence-context.

Before this, PATCH accepted a ``sequence`` field but honoured ONLY ``null`` — a
client sending a real sequence got HTTP 200 and no change (a silent-success trap).
It now sets the sequence for real, with validation and overhang write-back.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Direction, Domain, Helix, LoopSkip, OverhangSpec, Strand, StrandType, Vec3,
)

client = TestClient(app)


def _plain(*, loop_skips=(), scaffold_seq="AAAACCCC"):
    """A sequenced 8-bp scaffold + one antiparallel staple over it."""
    h = Helix(id="h0", axis_start=Vec3(x=0, y=0, z=0),
              axis_end=Vec3(x=0, y=0, z=8 * BDNA_RISE_PER_BP),
              phase_offset=0.0, length_bp=8, grid_pos=(0, 0),
              loop_skips=list(loop_skips))
    scaf = Strand(id="scaf", strand_type=StrandType.SCAFFOLD, domains=[
        Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD)],
        sequence=scaffold_seq)
    stap = Strand(id="stap", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="h0", start_bp=7, end_bp=0, direction=Direction.REVERSE)])
    return _demo_design().model_copy(update={
        "helices": [h], "strands": [scaf, stap], "overhangs": [],
    })


def _with_overhang(*, oh_seq="ACGTACGT", sub_domain_override=None):
    """A staple whose 3' domain is an 8-nt overhang tip, plus an 8-bp duplex body."""
    h = Helix(id="h0", axis_start=Vec3(x=0, y=0, z=0),
              axis_end=Vec3(x=0, y=0, z=8 * BDNA_RISE_PER_BP),
              phase_offset=0.0, length_bp=8, grid_pos=(0, 0))
    oh_h = Helix(id="oh_h", axis_start=Vec3(x=3, y=0, z=0),
                 axis_end=Vec3(x=3, y=0, z=8 * BDNA_RISE_PER_BP),
                 phase_offset=0.0, length_bp=8, grid_pos=(0, 3))
    scaf = Strand(id="scaf", strand_type=StrandType.SCAFFOLD, domains=[
        Domain(helix_id="h0", start_bp=0, end_bp=7, direction=Direction.FORWARD)],
        sequence="AAAACCCC")
    stap = Strand(id="stap", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="h0", start_bp=7, end_bp=0, direction=Direction.REVERSE),
        Domain(helix_id="oh_h", start_bp=0, end_bp=7, direction=Direction.FORWARD,
               overhang_id="oh_a")])
    spec = OverhangSpec(id="oh_a", helix_id="oh_h", strand_id="stap",
                        label="OH_A", sequence=oh_seq)
    if sub_domain_override is not None:
        subs = list(spec.sub_domains or [])
        subs[0] = subs[0].model_copy(update={"sequence_override": sub_domain_override})
        spec = spec.model_copy(update={"sub_domains": subs})
    return _demo_design().model_copy(update={
        "helices": [h, oh_h], "strands": [scaf, stap], "overhangs": [spec],
    })


def _strand(sid="stap"):
    return next(s for s in design_state.get_or_404().strands if s.id == sid)


def _overhang(oid="oh_a"):
    return next(o for o in design_state.get_or_404().overhangs if o.id == oid)


def _patch(seq, sid="stap"):
    return client.patch(f"/api/design/strand/{sid}", json={"sequence": seq})


# ── Write: accept / normalize ─────────────────────────────────────────────────


def test_sets_a_valid_sequence():
    design_state.close_session(); design_state.set_design(_plain())
    r = _patch("TTTTGGGG")
    assert r.status_code == 200, r.text
    assert _strand().sequence == "TTTTGGGG"


def test_normalizes_lowercase_and_whitespace():
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch(" tttt\n gggg ").status_code == 200
    assert _strand().sequence == "TTTTGGGG"


def test_allows_a_deliberately_mismatched_sequence():
    """The user must be able to enter ANY bases — mismatches are flagged in the
    UI, never rejected."""
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("AAAAAAAA").status_code == 200          # derived would be GGGGTTTT
    assert _strand().sequence == "AAAAAAAA"


def test_n_bases_are_accepted():
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("NNNNGGGG").status_code == 200
    assert _strand().sequence == "NNNNGGGG"


# ── Write: reject ─────────────────────────────────────────────────────────────


def test_rejects_invalid_characters():
    design_state.close_session(); design_state.set_design(_plain())
    r = _patch("TTTTGGGX")
    assert r.status_code == 422
    assert "X" in r.json()["detail"]
    assert _strand().sequence is None                     # unchanged


def test_rejects_wrong_length():
    design_state.close_session(); design_state.set_design(_plain())
    r = _patch("TTTT")
    assert r.status_code == 422
    assert "8" in r.json()["detail"]
    assert _strand().sequence is None


def test_length_check_honours_a_skip():
    """A skip removes a nucleotide, so the accepted length drops to 7."""
    design_state.close_session()
    design_state.set_design(_plain(loop_skips=[LoopSkip(bp_index=3, delta=-1)]))
    assert _patch("TTTTGGGG").status_code == 422          # 8 no longer fits
    assert _patch("TTTGGGG").status_code == 200
    assert _strand().sequence == "TTTGGGG"


def test_length_check_honours_a_loop():
    """A loop adds a nucleotide, so the accepted length rises to 9."""
    design_state.close_session()
    design_state.set_design(_plain(loop_skips=[LoopSkip(bp_index=3, delta=1)]))
    assert _patch("TTTTGGGG").status_code == 422
    assert _patch("TTTTTGGGG").status_code == 200
    assert _strand().sequence == "TTTTTGGGG"


def test_unknown_strand_404s():
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("TTTTGGGG", sid="nope").status_code == 404


# ── Write: overhang write-back ────────────────────────────────────────────────


def test_overhang_span_is_written_back_to_the_spec():
    design_state.close_session(); design_state.set_design(_with_overhang())
    # 8 duplex nt + 8 overhang nt, 5'→3'.
    assert _patch("GGGGTTTT" + "CCCCAAAA").status_code == 200
    assert _strand().sequence == "GGGGTTTTCCCCAAAA"
    assert _overhang().sequence == "CCCCAAAA"


def test_overhang_write_back_does_not_resize_the_domain():
    """Guard: _build_overhang_patch resizes an overhang to len(sequence). The
    write-back must NOT go through it — the tip's bp extent must be untouched."""
    design_state.close_session(); design_state.set_design(_with_overhang())
    before = [(d.helix_id, d.start_bp, d.end_bp) for d in _strand().domains]
    helix_before = next(h.length_bp for h in design_state.get_or_404().helices if h.id == "oh_h")
    assert _patch("GGGGTTTT" + "CCCCAAAA").status_code == 200
    after = [(d.helix_id, d.start_bp, d.end_bp) for d in _strand().domains]
    helix_after = next(h.length_bp for h in design_state.get_or_404().helices if h.id == "oh_h")
    assert after == before
    assert helix_after == helix_before


def test_write_back_skipped_when_sub_domain_override_present():
    """Those bases are owned per sub-domain (Domain Designer); the spec must not
    be rewritten from the strand field."""
    design_state.close_session()
    design_state.set_design(_with_overhang(sub_domain_override="TTTTTTTT"))
    assert _patch("GGGGTTTT" + "CCCCAAAA").status_code == 200
    assert _strand().sequence == "GGGGTTTTCCCCAAAA"       # strand field still set
    assert _overhang().sequence == "ACGTACGT"             # spec untouched


# ── Write: clear + undo + feature log ─────────────────────────────────────────


def test_null_still_clears():
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("TTTTGGGG").status_code == 200
    assert _patch(None).status_code == 200
    assert _strand().sequence is None


def test_clearing_also_clears_the_overhang_spec():
    design_state.close_session(); design_state.set_design(_with_overhang())
    assert _patch(None).status_code == 200
    assert _overhang().sequence is None


def test_undo_reverts_a_manual_sequence():
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("TTTTGGGG").status_code == 200
    assert client.post("/api/design/undo").status_code == 200
    assert _strand().sequence is None


def test_records_a_strand_sequence_feature_log_entry():
    """A sequence is a build-fingerprint field, so it must be a real feature-log
    step — otherwise a seek cannot reproduce it and a stale-job ⚠ never clears."""
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("TTTTGGGG").status_code == 200
    log = design_state.get_or_404().feature_log
    assert log and log[-1].op_kind == "strand-sequence"
    assert log[-1].params["sequence"] == "TTTTGGGG"


def test_notes_and_color_still_patch_without_touching_sequence():
    design_state.close_session(); design_state.set_design(_plain())
    assert _patch("TTTTGGGG").status_code == 200
    r = client.patch("/api/design/strand/stap", json={"notes": "hi", "color": "#ff0000"})
    assert r.status_code == 200, r.text
    s = _strand()
    assert s.notes == "hi" and s.color == "#ff0000"
    assert s.sequence == "TTTTGGGG"


# ── Read: sequence-context ────────────────────────────────────────────────────


def _ctx(sid="stap"):
    r = client.get(f"/api/design/strand/{sid}/sequence-context")
    assert r.status_code == 200, r.text
    return r.json()


def test_context_partner_is_the_antiparallel_scaffold_base():
    design_state.close_session(); design_state.set_design(_plain())
    c = _ctx()
    # Staple runs REVERSE 7→0; scaffold FORWARD is AAAACCCC over bp 0..7, so the
    # partner read in staple order is the scaffold reversed: CCCCAAAA.
    assert c["partner"] == "CCCCAAAA"
    assert c["length"] == 8
    assert c["sequence"] is None
    assert c["derived"] == "GGGGTTTT"        # complement of the partner


def test_context_lengths_are_all_aligned():
    design_state.close_session(); design_state.set_design(_with_overhang())
    c = _ctx()
    assert c["length"] == 16
    assert len(c["partner"]) == 16
    assert len(c["derived"]) == 16
    assert sum(seg["length"] for seg in c["segments"]) == 16


def test_context_marks_an_overhang_span_unpaired():
    design_state.close_session(); design_state.set_design(_with_overhang())
    c = _ctx()
    assert c["partner"][:8] == "CCCCAAAA"    # duplex body
    assert c["partner"][8:] == "-" * 8       # ssDNA tip has no partner


def test_context_segments_describe_the_domains():
    design_state.close_session(); design_state.set_design(_with_overhang())
    segs = _ctx()["segments"]
    assert [s["kind"] for s in segs] == ["duplex", "overhang"]
    assert segs[1] == {"start": 8, "length": 8, "kind": "overhang",
                       "overhang_id": "oh_a", "editable": True}


def test_context_marks_override_backed_overhang_not_editable():
    design_state.close_session()
    design_state.set_design(_with_overhang(sub_domain_override="TTTTTTTT"))
    segs = _ctx()["segments"]
    assert segs[1]["editable"] is False


def test_context_derived_is_null_when_scaffold_unsequenced():
    design_state.close_session(); design_state.set_design(_plain(scaffold_seq=None))
    c = _ctx()
    assert c["derived"] is None
    assert c["partner"] == "-" * 8


def test_context_404s_for_unknown_strand():
    design_state.close_session(); design_state.set_design(_plain())
    assert client.get("/api/design/strand/nope/sequence-context").status_code == 404
