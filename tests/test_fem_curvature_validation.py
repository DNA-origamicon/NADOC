"""CanDo FEM CURVATURE validation — automated, no CanDo web service needed.

Replicates the exp36 bend-battery curvature check (process_bend_battery.py, which
needs user-supplied CanDo ZIPs in ``workspace/cando validation/``) as a self-contained
pytest that regenerates the designs headlessly and asserts the native FEM reproduces
the *measured CanDo reference angles* within the calibrated envelope.

Reference angles (measured on the real honeycomb 6HB / 210 bp CanDo battery, 2026-07-03,
recorded in ``experiments/exp36_cando_fem_validation/cando_reference_values.json``):

    05_bend_90  : CanDo bend  86.9°  (R 45.9 nm)   — gentle bend
    06_bend_180 : CanDo bend 170.1°  (R 23.4 nm)   — hairpin (high strain)

The FEM reproduces CanDo bend to ~0.90 (linear) / ~0.95 (nonlinear) — see
``bend_diagnostics_results.md``.  The tests bracket that ratio.

Plus the NEGATIVE test the user asked for: a design with a bend applied ONLY as a
display-layer DeformationOp (``add_bend``) but whose loop/skips were NOT updated
(``apply_loop_skip_deformations`` deliberately skipped) — the FEM, which reads only the
topological loop/skip marks, must predict a STRAIGHT structure.  This pins the
Three-Layer Law: the physical/geometric layers never read the display deformation.

Bend is measured by :func:`tests.automation_harness.measure_fem_bundle_bend`
(chord+sagitta on the axis centerline — A9-safe: reads ~0 on a straight rod, the true
angle on an arc).  Marks depend only on per-helix NET loop/skip count, not exact bp
positions, so the FEM bend is identical to the exp36 battery even if mark placement differs.
"""
from __future__ import annotations


from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType
from tests.automation_harness import (
    assert_deformation_angle,
    assert_fem_matches_cando_bend,
    measure_fem_bundle_bend,
)

HC = LatticeType.HONEYCOMB
# Canonical 6HB honeycomb ring (matches gen_cando_battery.py + the conftest fixture).
SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
LEN = 210

# CanDo reference bend angles (deg) — cando_reference_values.json, honeycomb 6HB/210bp.
CANDO_BEND_90 = 86.9
CANDO_BEND_180 = 170.1


def _route_6hb(length: int = LEN) -> None:
    """Fully route a 6HB honeycomb bundle into ONE scaffold (create → auto_scaffold →
    auto_crossover → auto_break).  Loop/skips are realised AFTER this so autostaple only
    ever sees uniform cells — exactly the gen_cando_battery pipeline."""
    hb.create_bundle(SIX_HB_CELLS, length, lattice=HC, name="6hb")
    hb.auto_scaffold(seamless=False)
    hb.auto_crossover()
    hb.auto_break()


def _bend_design(total_deg: float, *, realize: bool):
    """Build a routed 6HB bundle with a ``total_deg`` end-to-end bend program.

    ``realize=True``  → bake the bend into loop/skip marks (topological; FEM sees it).
    ``realize=False`` → leave the bend as a display-only DeformationOp (FEM sees nothing).
    Returns a deep-copied Design detached from the scratch session.
    """
    with hb.scratch_session(HC):
        _route_6hb(LEN)
        hb.add_bend(0, LEN, curvature_deg_per_bp=total_deg / LEN)
        if realize:
            hb.apply_loop_skip_deformations()
        return design_state.get_or_404().model_copy(deep=True)


# ── Positive: FEM reproduces the CanDo bend ───────────────────────────────────

def test_fem_reproduces_cando_bend_90_linear():
    """05_bend_90: the fast LINEAR prestress solve reproduces CanDo's 86.9° bend to
    within the calibrated ~0.90 linear envelope (FEM ≈ 81°)."""
    d = _bend_design(90.0, realize=True)
    assert sum(len(h.loop_skips) for h in d.helices) > 0     # marks were realised
    m = assert_fem_matches_cando_bend(
        d, CANDO_BEND_90, nonlinear=False, ratio_lo=0.85, ratio_hi=1.08
    )
    # Radius of curvature is physical and near the CanDo reference (45.9 nm); the FEM
    # under-converts slightly → a somewhat larger R.  Loose sanity band only.
    assert 35.0 < m["radius_nm"] < 75.0


def test_fem_reproduces_cando_bend_90_nonlinear():
    """05_bend_90: the corotational NONLINEAR solve is the app default (nonlinear=True)
    and lands within ±8° of CanDo's 86.9° (FEM ≈ 85°)."""
    d = _bend_design(90.0, realize=True)
    m = measure_fem_bundle_bend(d, nonlinear=True, n_steps=8)
    assert abs(m["bend_deg"] - CANDO_BEND_90) < 8.0, m


def test_fem_reproduces_cando_bend_180_hairpin_linear():
    """06_bend_180: the high-strain hairpin.  Linear under-converts more here (~0.86),
    the documented soft spot; assert it still tracks CanDo's 170.1° within a looser band
    and is unambiguously a deep bend."""
    d = _bend_design(180.0, realize=True)
    assert_fem_matches_cando_bend(
        d, CANDO_BEND_180, nonlinear=False, ratio_lo=0.78, ratio_hi=1.10, min_bend_deg=120.0
    )


# ── Negative: display bend WITHOUT realized loop/skips → FEM predicts straight ──

def test_bend_deformation_without_loopskips_predicts_straight():
    """THE negative test (Three-Layer Law).  A design carrying a real ~90° bend as a
    display-layer DeformationOp — but whose loop/skips were NOT updated — must predict a
    STRAIGHT FEM shape, because the FEM reads only the topological loop/skip eigenstrain.

    Proven three ways:
      1. Topology carries NO loop/skip marks (the bend was never realised).
      2. The DISPLAY is genuinely bent — assert_deformation_angle reads ~82° across the
         deformed frame (so this isn't vacuously testing an un-bent design).
      3. The FEM-predicted bend is ~0° (straight) — the display deformation drove nothing.
    """
    d = _bend_design(90.0, realize=False)

    # 1. topology untouched — no marks were baked in
    assert sum(len(h.loop_skips) for h in d.helices) == 0

    # 2. the design really has a bend — the display DeformationOp rotates the frame ~86°
    #    across [0, 200] (expected 90·200/210 ≈ 85.7°; realised ≈ 82°, wide tol).
    assert_deformation_angle(d, 0, 200, 90.0 * 200 / LEN, angle_tol_deg=8.0)

    # 3. …yet the FEM predicts a straight rod (no topological strain to convert).
    m = measure_fem_bundle_bend(d, nonlinear=False)
    assert m["bend_deg"] < 3.0, (
        f"FEM predicted {m['bend_deg']:.2f}° of bend from a display-only DeformationOp — "
        "the physical layer must not read the display bend (Three-Layer Law violation)."
    )


def test_realized_vs_unrealized_bend_is_the_only_difference():
    """Direct contrast: the SAME 90° bend program predicts a deep FEM bend when realised
    to loop/skips and a straight shape when left as a display op — isolating the loop/skip
    realisation as the sole driver of the FEM prediction."""
    realized = measure_fem_bundle_bend(_bend_design(90.0, realize=True), nonlinear=False)
    display_only = measure_fem_bundle_bend(_bend_design(90.0, realize=False), nonlinear=False)
    assert realized["bend_deg"] > 60.0
    assert display_only["bend_deg"] < 3.0
