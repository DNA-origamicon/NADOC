"""CPD weld metrics — backend/core/cpd_metrics.py.

Two things are worth pinning here.

**Pair identity comes from topology, not proximity.** The intended UV weld is between the
extra bases of a *reciprocal* crossover pair. A design can carry extra bases on crossovers
that are not reciprocal partners (``Examples/2hb_xover_atoms_test.nadoc`` does) and those
must yield no weld pair at all — an off-target close approach is not a weld.

**The geometry is a cross-language contract.** ``weld_geometry`` exists twice: here for
analysis, and in ``frontend/src/md/cpd_geometry.js`` for the viewer, which must compute
from the coordinates it is already rendering rather than run a second coordinate pipeline.
Both assert against ``tests/fixtures/cpd_reference_cases.json``, so a drift in either one
goes red instead of silently putting a different number on screen than in the analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from backend.core import cpd_metrics as cm
from tests.test_junction_topology import _reciprocal_design

_REF = json.loads(
    (Path(__file__).parent / "fixtures" / "cpd_reference_cases.json").read_text())


# ── the cross-language geometry contract ──────────────────────────────────────


@pytest.mark.parametrize("case", _REF["cases"], ids=lambda c: c["name"])
def test_weld_geometry_matches_reference_case(case):
    got = cm.weld_geometry(case["c5_a"], case["c6_a"], case["c5_b"], case["c6_b"])
    assert got["d_nm"] == pytest.approx(case["d_nm"], abs=1e-9)
    assert got["eta_deg"] == pytest.approx(case["eta_deg"], abs=1e-6)
    assert got["k"] == pytest.approx(case["k"], abs=1e-9)
    assert got["reactive"] is case["reactive"]


def test_reference_constants_match_the_module():
    for name, value in _REF["constants"].items():
        assert getattr(cm, name) == value, f"{name} drifted from the shared fixture"


# ── geometry ──────────────────────────────────────────────────────────────────


def test_rate_is_one_at_the_product_geometry():
    assert cm.kimmdy_rate(cm.D0, cm.N0) == pytest.approx(1.0)


def test_rate_falls_off_with_distance_and_twist():
    assert cm.kimmdy_rate(0.34, 0.0) > cm.kimmdy_rate(0.60, 0.0)
    assert cm.kimmdy_rate(0.34, 0.0) > cm.kimmdy_rate(0.34, 90.0)


def test_angular_separation_takes_the_short_way_round():
    """The upstream KIMMDY model uses a plain abs(eta - eta0), which at -175 deg returns
    191.7 where the true separation is 168.3 — underestimating the rate ~2x. We do not
    inherit that."""
    assert cm.angular_separation_deg(-175.0) == pytest.approx(168.256348, abs=1e-5)
    assert cm.angular_separation_deg(cm.N0) == pytest.approx(0.0)
    naive = abs(-175.0 - cm.N0)
    assert naive > cm.angular_separation_deg(-175.0)


def test_angular_separation_never_exceeds_180():
    etas = np.linspace(-180.0, 180.0, 721)
    assert cm.angular_separation_deg(etas).max() <= 180.0 + 1e-9


def test_dihedral_of_a_planar_cis_arrangement_is_zero():
    assert cm.dihedral_deg([0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 1, 0]) == pytest.approx(0.0)


def test_dihedral_sign_flips_with_the_mirror_image():
    a = cm.dihedral_deg([0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 0.5, 0.5])
    b = cm.dihedral_deg([0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 0.5, -0.5])
    assert a == pytest.approx(-b)
    assert abs(a) > 1e-6


def test_d_mid_is_the_bond_midpoint_distance_not_the_c5_c5_distance():
    """The KIMMDY expression 0.5*((C5b-C5a)+(C6b-C6a)) simplifies to the distance between
    the two C5=C6 bond midpoints. Using C5-C5 instead is a different number."""
    c5a, c6a = np.array([0.0, 0, 0]), np.array([0.139, 0, 0])
    c5b, c6b = np.array([0.139, 0, 0.34]), np.array([0.0, 0, 0.34])   # flipped bond
    got = cm.weld_geometry(c5a, c6a, c5b, c6b)
    assert got["d_nm"] == pytest.approx(0.34, abs=1e-9)               # midpoints align
    assert np.linalg.norm(c5b - c5a) > 0.36                           # C5-C5 does not


# ── pair identity from topology ───────────────────────────────────────────────


def test_one_extra_base_per_crossover_gives_exactly_one_weld_pair():
    pairs = cm.designed_weld_pairs(_reciprocal_design("T"))
    assert len(pairs) == 1
    p = pairs[0]
    assert p["extra_base_k_a"] == 0 and p["extra_base_k_b"] == 0
    assert p["segid_a"] != p["segid_b"], "the two inserts ride different strands"


def test_two_extra_bases_per_crossover_give_four_combinations():
    pairs = cm.designed_weld_pairs(_reciprocal_design("TT"))
    assert len(pairs) == 4
    assert {(p["extra_base_k_a"], p["extra_base_k_b"]) for p in pairs} == {
        (0, 0), (0, 1), (1, 0), (1, 1)}
    assert len({p["id"] for p in pairs}) == 4, "pair ids must be unique"


def test_no_extra_bases_means_no_weld_pairs():
    assert cm.designed_weld_pairs(_reciprocal_design(None)) == []
    assert cm.designed_weld_pairs(_reciprocal_design("")) == []


def test_extra_bases_on_non_reciprocal_crossovers_are_not_a_weld():
    """Pair identity is design intent, not proximity. This example carries extra bases on
    two crossovers that are NOT reciprocal partners, so there is nothing to weld."""
    from backend.core.models import Design

    path = Path(__file__).parent.parent / "Examples" / "2hb_xover_atoms_test.nadoc"
    if not path.exists():
        pytest.skip("example design not present")
    design = Design(**json.loads(path.read_text()))
    assert any(x.extra_bases for x in (design.crossovers or [])), "fixture lost its inserts"
    assert cm.designed_weld_pairs(design) == []


def test_insert_residue_numbering_uses_the_builder_segid_convention():
    pairs = cm.designed_weld_pairs(_reciprocal_design("T"))
    p = pairs[0]
    for seg in (p["segid_a"], p["segid_b"]):
        assert seg.startswith("D") and seg[1:].isdigit() and len(seg) == 4
    assert p["resid_a"] >= 1 and p["resid_b"] >= 1


# ── serial resolution degrades rather than raising ────────────────────────────


class _FakeUniverse:
    """select_atoms that never matches — stands in for a topology packaged from a
    different design."""

    def select_atoms(self, _sel):
        raise IndexError("no such residue")


def test_unresolvable_serials_degrade_instead_of_raising():
    pairs = cm.designed_weld_pairs(_reciprocal_design("T"))
    out = cm.resolve_weld_serials(pairs, _FakeUniverse())
    assert len(out) == 1
    assert out[0]["serials_resolved"] is False
    assert out[0]["id"] == pairs[0]["id"], "identity survives even without serials"
    assert "c5_a" not in out[0]


def test_resolve_weld_serials_does_not_mutate_its_input():
    pairs = cm.designed_weld_pairs(_reciprocal_design("T"))
    before = json.dumps(pairs, sort_keys=True)
    cm.resolve_weld_serials(pairs, _FakeUniverse())
    assert json.dumps(pairs, sort_keys=True) == before


# ── trajectory trace ──────────────────────────────────────────────────────────


def test_trace_stride_widens_rather_than_truncating():
    """A truncated series over the first N frames of a long run reads as 'never got
    close' when the run simply was not looked at past frame N. The trace must always
    span the WHOLE run."""
    step = cm.trace_stride(100_000, stride=1, max_frames=2000)
    assert 100_000 // step <= 2000
    assert step > 1


def test_trace_stride_respects_a_caller_stride_that_already_fits():
    assert cm.trace_stride(1000, stride=5, max_frames=2000) == 5


def test_trace_stride_never_returns_zero_or_negative():
    for n in (0, 1, 7, 1_000_000):
        for s in (0, -3, 1, 10):
            assert cm.trace_stride(n, stride=s, max_frames=10) >= 1


class _FakeFragment:
    def __init__(self, positions):
        self.positions = np.asarray(positions, dtype=float)

    def center_of_geometry(self):
        return self.positions.mean(axis=0)


class _FakeDna:
    """Stands in for an AtomGroup: records that unwrap was asked for, nothing more."""

    def __init__(self):
        self.unwrapped = False

    def unwrap(self, compound=None, inplace=False):
        self.unwrapped = True


def test_make_whole_dna_brings_a_strand_back_from_a_neighbouring_image():
    """Per-fragment unwrap alone leaves strands in different periodic images. Skipping
    this second step produced plausible-looking nonsense (a rigid duplex appeared to move
    ~9 A) rather than any error — which is why it is pinned."""
    box = np.array([100.0, 100.0, 100.0])
    a = _FakeFragment([[10.0, 10.0, 10.0], [12.0, 10.0, 10.0]])
    b = _FakeFragment([[111.0, 10.0, 10.0], [113.0, 10.0, 10.0]])   # one box over in x
    dna = _FakeDna()

    cm.make_whole_dna(dna, [a, b], box)

    assert dna.unwrapped
    # b is pulled back next to a, not left 100 A away
    assert b.positions[0][0] == pytest.approx(11.0)
    assert abs(b.center_of_geometry()[0] - a.center_of_geometry()[0]) < 10.0


def test_make_whole_dna_leaves_an_already_whole_assembly_untouched():
    box = np.array([100.0, 100.0, 100.0])
    a = _FakeFragment([[10.0, 10.0, 10.0]])
    b = _FakeFragment([[14.0, 10.0, 10.0]])
    before = b.positions.copy()

    cm.make_whole_dna(_FakeDna(), [a, b], box)

    assert np.allclose(b.positions, before)


def test_weld_trace_reports_no_pairs_as_a_ready_result_not_an_error():
    """Most designs have no weld pair; that is information, not a failure."""
    out = cm.weld_trace("unused.psf", [], _reciprocal_design(None))
    assert out["ready"] is True
    assert out["pairs"] == []
    assert "reciprocal" in out["reason"]
