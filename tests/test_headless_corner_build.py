"""Headless mitred-corner primitive (backend/api/headless_corner_build.py).

The design-automation primitive that builds a 90° corner from two SQUARE sheets
with a phase-aware scaffold-length optimiser, validated against the shipped
design-layer clash detector (backend/core/clash.py).  See the module docstring for
the two-constraint principle.
"""

from pathlib import Path

import pytest

from backend.api.headless_corner_build import (
    _default_col_offset,
    _ideal_lengths,
    build_corner,
    corner_face_angle_deg,
    forced_ligation_stretches,
    resolve_corner_spec,
    steric_clash_count,
)
from backend.core.models import Design, LatticeType
from tests.automation_harness import assert_corner_folded

_REFERENCE = Path(__file__).resolve().parent / "fixtures" / "corner_miter_test.nadoc"

# The human-tuned reference number this must match or beat (see the task / clash.py
# calibration): total posed forced-ligation stretch ≈ 3.43 nm, max ≈ 0.94 nm.
_REFERENCE_TOTAL_NM = 3.43


# ── Pure helpers ─────────────────────────────────────────────────────────────────


def test_ideal_lengths_are_the_axial_miter_stagger():
    # base − round(i·2.25/0.334); the 45° staircase (constraint #1 only).
    assert _ideal_lengths(6, 56) == (56, 49, 43, 36, 29, 22)


def test_default_col_offset_is_odd_and_leaves_a_gap():
    for n in range(2, 12):
        off = _default_col_offset(n)
        assert off % 2 == 1, f"offset for n={n} must be odd (parity flip)"
        assert off >= n, f"offset for n={n} must not overlap the sheets"


# ── Build guards ─────────────────────────────────────────────────────────────────


def test_rejects_non_square_lattice():
    with pytest.raises(ValueError, match="SQUARE"):
        build_corner(lattice=LatticeType.HONEYCOMB)


def test_rejects_non_90_degree_target():
    with pytest.raises(ValueError, match="90"):
        build_corner(target_angle_deg=120)


def test_rejects_even_col_offset():
    with pytest.raises(ValueError, match="ODD"):
        build_corner(col_offset=8)


# ── Structure of the built corner ───────────────────────────────────────────────


def test_unoptimized_corner_has_the_expected_shape():
    d = build_corner(optimize=False)
    spec = resolve_corner_spec(d)
    assert spec.n_helices == 6
    assert spec.a_cols == (0, 1, 2, 3, 4, 5)
    assert spec.b_cols == (9, 10, 11, 12, 13, 14)
    # uniform axial-exact miter lengths, both sheets identical
    assert spec.a_len == spec.ideal and spec.b_len == spec.ideal
    # two clusters (one per sheet), 6 seam ligations, 12 helices
    assert len(d.helices) == 12
    assert len(d.forced_ligations) == 6
    assert len([c for c in d.cluster_transforms if not c.is_default]) == 2


def test_corner_folds_to_ninety_degrees():
    # length-only build (cheap) — the fold-optimised angle is checked in the fold test
    d = build_corner(optimize=True, optimize_fold=False)
    angle = corner_face_angle_deg(d, resolve_corner_spec(d))
    assert abs(angle - 90.0) <= 5.0, f"corner angle {angle:.1f}° not ~90°"


# ── The optimiser beats the reference (the point of the task) ────────────────────


def test_length_optimizer_beats_uniform_baseline_and_reference():
    uniform = build_corner(optimize=False)
    optimized = build_corner(optimize=True, optimize_fold=False)

    uni_total = sum(forced_ligation_stretches(uniform))
    opt_total = sum(forced_ligation_stretches(optimized))
    opt_max = max(forced_ligation_stretches(optimized))

    # the length optimiser strictly helps vs the uniform (axial-only) stagger …
    assert opt_total < uni_total, (
        f"optimiser did not help: optimised {opt_total:.3f} nm vs uniform {uni_total:.3f} nm"
    )
    # … and matches or beats the human-tuned reference, with every bond short.
    assert opt_total <= _REFERENCE_TOTAL_NM, (
        f"optimised total {opt_total:.3f} nm did not match/beat the reference "
        f"{_REFERENCE_TOTAL_NM} nm"
    )
    assert opt_max < 1.0, f"an optimised seam bond is over-stretched: {opt_max:.3f} nm"


def test_length_optimizer_does_not_worsen_steric_clashes():
    uniform = build_corner(optimize=False)
    optimized = build_corner(optimize=True, optimize_fold=False)
    # genuine steric clashes (seam FL bonds excluded — a designed bond is not a clash)
    assert steric_clash_count(optimized) <= steric_clash_count(uniform)


def test_fold_optimizer_reduces_clashes_and_beats_reference():
    # The fold-pose optimiser is the clash lever: the tight-bonds-only build packs the
    # seam (~24 genuine clashes); tuning the fold pose drops that substantially while
    # keeping every bond short — beating the human-tuned reference on BOTH axes.
    lengths_only = build_corner(optimize=True, optimize_fold=False)
    co_optimized = build_corner(optimize=True, optimize_fold=True)

    lo_clash = steric_clash_count(lengths_only)
    co_clash = steric_clash_count(co_optimized)
    assert co_clash < lo_clash, (
        f"fold optimiser did not reduce clashes: {co_clash} vs lengths-only {lo_clash}"
    )
    # beats the reference on clashes (≤ 11) …
    assert co_clash <= 11, (
        f"fold-optimised clashes {co_clash} did not match/beat the reference 11"
    )

    stretches = forced_ligation_stretches(co_optimized)
    # … while every seam bond stays short and the total still beats the reference.
    assert max(stretches) < 1.0, (
        f"a co-optimised seam bond is over-stretched: {max(stretches):.3f} nm"
    )
    assert sum(stretches) <= _REFERENCE_TOTAL_NM, (
        f"co-optimised total {sum(stretches):.3f} nm did not beat the reference {_REFERENCE_TOTAL_NM} nm"
    )
    # the fold stayed a valid ~90° corner
    angle = corner_face_angle_deg(co_optimized, resolve_corner_spec(co_optimized))
    assert abs(angle - 90.0) <= 5.0, (
        f"co-optimised corner angle {angle:.1f}° drifted too far"
    )


# ── Full oracle (all layers + round-trip + logged fold) ─────────────────────────


def test_corner_passes_the_full_oracle():
    uniform = build_corner(optimize=False)
    baseline_total = sum(forced_ligation_stretches(uniform))
    baseline_clashes = steric_clash_count(uniform)

    optimized = build_corner(optimize=True, optimize_fold=True)
    assert_corner_folded(
        optimized,
        n_helices=6,
        target_angle_deg=90.0,
        max_stretch_nm=1.0,
        baseline_total_nm=baseline_total,
        baseline_steric_clashes=baseline_clashes,
    )


def test_oracle_fires_on_an_unfolded_design():
    # A flat (unfolded) two-sheet build must fail the corner-angle clause — proves
    # the oracle can go red.
    from backend.api import headless_build as hb
    from backend.api import headless_corner_build as hc

    with hb.scratch_session(LatticeType.SQUARE):
        spec = hc.CornerSpec(
            n_helices=6,
            base_length_bp=56,
            col_offset=9,
            a_cols=(0, 1, 2, 3, 4, 5),
            b_cols=(9, 10, 11, 12, 13, 14),
            a_len=hc._ideal_lengths(6, 56),
            b_len=hc._ideal_lengths(6, 56),
            ideal=hc._ideal_lengths(6, 56),
        )
        hc._lay_sheets(spec, spec.a_len, spec.b_len, create_len=56)
        hc._seam_ligations(spec)  # ligate WITHOUT folding
        flat = hc.design_state.get_or_404().model_copy(deep=True)
    with pytest.raises(AssertionError):
        assert_corner_folded(flat, n_helices=6)


# ── Parameterisation: a smaller corner also works ───────────────────────────────


def test_four_helix_corner_builds_and_validates():
    # exercises the fold optimiser at a different N (no hard-coded seam count)
    d = build_corner(n_helices=4, base_length_bp=48, optimize=True, optimize_fold=False)
    spec = resolve_corner_spec(d)
    assert spec.n_helices == 4
    assert len(d.forced_ligations) == 4
    assert_corner_folded(d, n_helices=4)


# ── Reference fixture sanity (the calibration target the clash detector uses) ────


@pytest.mark.skipif(not _REFERENCE.exists(), reason="corner_miter_test fixture missing")
def test_reference_fixture_matches_stated_metrics():
    ref = Design.from_json(_REFERENCE.read_text(encoding="utf-8"))
    stretches = forced_ligation_stretches(ref)
    assert len(stretches) == 6
    # the reference's stated numbers: total ≈ 3.43 nm, max ≈ 0.94 nm
    assert abs(sum(stretches) - 3.43) < 0.05
    assert abs(max(stretches) - 0.94) < 0.05
