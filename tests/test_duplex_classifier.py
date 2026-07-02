"""Phase 1 — per-base Duplex pairing classifier + coverage oracle (pure core).

Exercises ``classify_duplex_pairing`` / ``overhang_pairing_map`` /
``summarize_duplexes`` directly on hand-built designs so mismatched registers
(which CRUD still rejects while the WC gate is kept) can be classified. See
``memory/project_overhang_duplex_foundation.md``.
"""
from __future__ import annotations

from backend.core.duplex import (
    classify_duplex_pairing, overhang_pairing_map, summarize_duplexes,
)
from backend.core.models import (
    Design, Direction, Domain, Duplex, DuplexEnd, OverhangSpec, Strand, StrandType,
)


def _design(seq_a="AAACGG", seq_b="GTTTCC", duplexes=None) -> Design:
    """Overhang A on forward domain [0,5], overhang B on reverse domain [5,0]."""
    sa = Strand(id="st_a", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hA", start_bp=0, end_bp=5,
                                direction=Direction.FORWARD, overhang_id="ohA")])
    sb = Strand(id="st_b", strand_type=StrandType.STAPLE,
                domains=[Domain(helix_id="hB", start_bp=5, end_bp=0,
                                direction=Direction.REVERSE, overhang_id="ohB")])
    ohA = OverhangSpec(id="ohA", helix_id="hA", strand_id="st_a", sequence=seq_a)
    ohB = OverhangSpec(id="ohB", helix_id="hB", strand_id="st_b", sequence=seq_b)
    return Design(strands=[sa, sb], overhangs=[ohA, ohB], duplexes=duplexes or [])


def _dx(a_lo, a_hi, b_lo, b_hi, **kw):
    return Duplex(left=DuplexEnd(overhang_id="ohA", start_bp=a_lo, end_bp=a_hi),
                  right=DuplexEnd(overhang_id="ohB", start_bp=b_lo, end_bp=b_hi), **kw)


def test_classify_all_complementary():
    # left "AAAC" (bp0..3) vs right "GTTT" (bp5..2) — antiparallel RC → all paired.
    d = _design(duplexes=[_dx(0, 3, 5, 2)])
    cls = classify_duplex_pairing(d, d.duplexes[0])
    assert cls["length"] == 4
    assert cls["n_complementary"] == 4 and cls["n_mismatch"] == 0
    # antiparallel register: left 5' base (bp0) pairs right 3' base (bp2).
    assert cls["positions"][0]["left_bp"] == 0 and cls["positions"][0]["right_bp"] == 2


def test_classify_counts_mismatches():
    # right sequence made non-complementary → every position mismatches.
    d = _design(seq_b="AAACCC", duplexes=[_dx(0, 3, 5, 2)])
    cls = classify_duplex_pairing(d, d.duplexes[0])
    assert cls["n_mismatch"] == 4 and cls["n_complementary"] == 0


def test_pairing_map_reports_toehold():
    # 4 bp duplex on a 6 bp overhang → bp 4,5 uncovered = toehold (unpaired).
    d = _design(duplexes=[_dx(0, 3, 5, 2)])
    cov = overhang_pairing_map(d, "ohA")
    assert [cov[bp] for bp in range(6)] == ['paired'] * 4 + ['unpaired'] * 2


def test_pairing_map_reports_mismatch():
    d = _design(seq_b="AAACCC", duplexes=[_dx(0, 3, 5, 2)])
    cov = overhang_pairing_map(d, "ohA")
    assert cov[0] == 'mismatch' and cov[5] == 'unpaired'


def test_pairing_map_multivalent_two_partners_disjoint():
    # ohA covered on bp0-1 AND bp4-5 by two duplexes, bp2-3 a middle toehold.
    # Assert coverage structure (covered vs uncovered), independent of WC.
    d = _design(duplexes=[_dx(0, 1, 5, 4), _dx(4, 5, 1, 0)])
    cov = overhang_pairing_map(d, "ohA")
    assert cov[2] == 'unpaired' and cov[3] == 'unpaired'   # middle toehold
    for bp in (0, 1, 4, 5):
        assert cov[bp] != 'unpaired'                        # covered by a duplex


def test_summarize_duplexes_oracle():
    d = _design(duplexes=[_dx(0, 3, 5, 2, driver="right", bound=True)])
    s = summarize_duplexes(d)
    assert s["duplexes"][0]["n_complementary"] == 4
    assert s["duplexes"][0]["driver"] == "right" and s["duplexes"][0]["bound"] is True
    assert s["overhangs"]["ohA"] == {"paired": 4, "mismatch": 0, "toehold": 2}
