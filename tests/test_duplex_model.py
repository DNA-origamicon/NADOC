"""Phase 0 — Proposal-B Duplex model + migration (behavior-neutral).

Covers the new register-bearing pairing edge (``Duplex`` / ``DuplexEnd``), the
``Design._validate_duplexes`` cross-checks, the offset↔bp conversion, and the
standalone ``synthesize_duplexes_from_bindings`` migration from legacy
``OverhangBinding`` records. Nothing here exercises geometry or CRUD — those are
later phases. See ``memory/project_overhang_duplex_foundation.md``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.duplex import (
    offset_to_bp, subdomain_end, synthesize_duplexes_from_bindings,
    shift_duplex_ends, drop_invalid_duplexes,
)
from backend.core.models import (
    Design, Direction, Domain, Duplex, DuplexEnd, OverhangBinding,
    OverhangSpec, Strand, StrandType, SubDomain,
)


# ── Fixture: two overhangs, one FORWARD (bp 0..5) and one REVERSE (bp 5..0) ────

def _mk_design(*, duplexes=None, bindings=None) -> Design:
    """Minimal design: overhang A on a forward domain [0,5], overhang B on a
    reverse domain [5,0]. Each carries a 4 nt sub-domain at its 5' end so the
    migration has something to convert. Helices are unnecessary — the duplex
    validator only reads the backing domains."""
    strand_a = Strand(
        id="st_a", strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="hA", start_bp=0, end_bp=5,
                        direction=Direction.FORWARD, overhang_id="ohA")],
    )
    strand_b = Strand(
        id="st_b", strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="hB", start_bp=5, end_bp=0,
                        direction=Direction.REVERSE, overhang_id="ohB")],
    )
    ohA = OverhangSpec(
        id="ohA", helix_id="hA", strand_id="st_a", sequence="AAACGG",
        sub_domains=[SubDomain(id="sdA", name="a", start_bp_offset=0, length_bp=4)],
    )
    ohB = OverhangSpec(
        id="ohB", helix_id="hB", strand_id="st_b", sequence="GTTTCC",
        sub_domains=[SubDomain(id="sdB", name="b", start_bp_offset=0, length_bp=4)],
    )   # sdB = "GTTT" = antiparallel WC of sdA "AAAC" → legacy binding validator passes
    return Design(
        strands=[strand_a, strand_b], overhangs=[ohA, ohB],
        duplexes=duplexes or [], overhang_bindings=bindings or [],
    )


def _end(oid, s, e):
    return DuplexEnd(overhang_id=oid, start_bp=s, end_bp=e)


# ── offset ↔ bp (mirrors sequences.py) ────────────────────────────────────────

def test_offset_to_bp_forward_and_reverse():
    fwd = Domain(helix_id="hA", start_bp=0, end_bp=5, direction=Direction.FORWARD)
    rev = Domain(helix_id="hB", start_bp=5, end_bp=0, direction=Direction.REVERSE)
    assert offset_to_bp(fwd, 0) == 0 and offset_to_bp(fwd, 3) == 3   # 5'→3' rising
    assert offset_to_bp(rev, 0) == 5 and offset_to_bp(rev, 3) == 2   # 5'→3' falling


# ── Model-level validators (Duplex self-consistency) ──────────────────────────

def test_duplex_equal_length_ok_and_unequal_rejected():
    Duplex(left=_end("ohA", 0, 3), right=_end("ohB", 5, 2))          # both 4 bp — ok
    with pytest.raises(ValidationError, match="equal length"):
        Duplex(left=_end("ohA", 0, 3), right=_end("ohB", 5, 3))      # 4 vs 3


def test_duplex_self_overlap_on_same_overhang_rejected():
    with pytest.raises(ValidationError, match="cannot pair itself"):
        Duplex(left=_end("ohA", 0, 3), right=_end("ohA", 2, 5))      # share bp 2,3


# ── Design-level validator (_validate_duplexes) ───────────────────────────────

def test_valid_duplex_passes_design_validation():
    d = _mk_design(duplexes=[Duplex(left=_end("ohA", 0, 3), right=_end("ohB", 5, 2))])
    assert len(d.duplexes) == 1


def test_empty_duplexes_is_noop_backward_compat():
    assert _mk_design().duplexes == []   # pre-Phase-0 designs load untouched


def test_out_of_domain_interval_rejected():
    with pytest.raises(ValidationError, match="outside overhang"):
        _mk_design(duplexes=[Duplex(left=_end("ohA", 0, 9), right=_end("ohB", 5, -4))])


def test_unresolved_overhang_rejected():
    with pytest.raises(ValidationError, match="does not resolve"):
        _mk_design(duplexes=[Duplex(left=_end("nope", 0, 3), right=_end("ohB", 5, 2))])


def test_double_pairing_a_base_rejected():
    # Two duplexes both claim bp 2,3 on ohA → a base would pair twice.
    with pytest.raises(ValidationError, match="already paired"):
        _mk_design(duplexes=[
            Duplex(left=_end("ohA", 0, 3), right=_end("ohB", 5, 2)),
            Duplex(left=_end("ohA", 2, 5), right=_end("ohB", 3, 0)),
        ])


def test_multivalency_disjoint_ranges_ok():
    # One long overhang paired to two partners on DISJOINT bp ranges is allowed.
    d = _mk_design(duplexes=[
        Duplex(left=_end("ohA", 0, 1), right=_end("ohB", 5, 4)),
        Duplex(left=_end("ohA", 2, 3), right=_end("ohB", 3, 2)),
    ])
    assert len(d.duplexes) == 2


# ── cadnano-drag reconcile (shift preserves register; resize drops out-of-range) ─

def test_shift_duplex_ends_preserves_register():
    d = _mk_design(duplexes=[Duplex(left=_end("ohA", 0, 3), right=_end("ohB", 5, 2))])
    out = shift_duplex_ends(d, {"ohA": 2})   # ohA moved +2 bp
    dx = out.duplexes[0]
    assert (dx.left.start_bp, dx.left.end_bp) == (2, 5)   # ohA end shifted with the move
    assert (dx.right.start_bp, dx.right.end_bp) == (5, 2)  # ohB end untouched


def test_drop_invalid_duplexes_drops_out_of_range_but_keeps_valid():
    d = _mk_design(duplexes=[Duplex(left=_end("ohA", 0, 3), right=_end("ohB", 5, 2))])
    assert len(drop_invalid_duplexes(d).duplexes) == 1        # valid → kept
    # Shrink ohA's backing domain to [0,2] WITHOUT re-validating (model_copy),
    # mimicking the transient post-resize state; the [0,3] register no longer fits.
    dom = d.strands[0].domains[0].model_copy(update={"end_bp": 2})
    shrunk = d.model_copy(update={"strands": [
        d.strands[0].model_copy(update={"domains": [dom]}), d.strands[1]]})
    assert drop_invalid_duplexes(shrunk).duplexes == []       # out-of-range → dropped


# ── Migration from legacy OverhangBinding ─────────────────────────────────────

def _binding(**kw):
    base = dict(name="B1", sub_domain_a_id="sdA", sub_domain_b_id="sdB",
                overhang_a_id="ohA", overhang_b_id="ohB")
    base.update(kw)
    return OverhangBinding(**base)


def test_migration_converts_binding_to_duplex_with_bp_and_driver():
    design = _mk_design(bindings=[_binding(bound=True, driver_oh_id="ohB")])
    dux = synthesize_duplexes_from_bindings(design)
    assert len(dux) == 1
    dx = dux[0]
    # left = ohA forward sub-domain [offset 0..3] → bp 0..3
    assert (dx.left.overhang_id, dx.left.start_bp, dx.left.end_bp) == ("ohA", 0, 3)
    # right = ohB reverse sub-domain [offset 0..3] → bp 5..2
    assert (dx.right.overhang_id, dx.right.start_bp, dx.right.end_bp) == ("ohB", 5, 2)
    assert dx.driver == "right"       # driver_oh_id == overhang_b_id
    assert dx.bound is True


def test_migrated_duplex_passes_design_validation():
    design = _mk_design(bindings=[_binding()])
    dux = synthesize_duplexes_from_bindings(design)
    # Re-inserting the synthesized duplex must satisfy _validate_duplexes.
    design.model_copy(update={"duplexes": dux})


def test_migration_default_driver_left_when_field_absent():
    design = _mk_design(bindings=[_binding()])   # no driver_oh_id
    assert synthesize_duplexes_from_bindings(design)[0].driver == "left"


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_json_round_trip_preserves_duplexes():
    d = _mk_design(duplexes=[Duplex(
        name="D1", left=_end("ohA", 0, 3), right=_end("ohB", 5, 2), driver="right",
        bound=True, connection_type="root-to-root",
    )])
    back = Design.model_validate_json(d.model_dump_json())
    assert len(back.duplexes) == 1
    dx = back.duplexes[0]
    assert dx.name == "D1" and dx.driver == "right" and dx.bound is True
    assert dx.left.start_bp == 0 and dx.right.end_bp == 2
    assert dx.connection_type == "root-to-root"
