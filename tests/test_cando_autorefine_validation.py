"""CanDo-FEM AUTOREFINE validation — automated, headless, no CanDo web service.

The engine bug the user hit on ``3x6x400_Sq_test.nadoc``: autorefine reported "0 edits /
no improvement" on a bare square strut.  A plain square bundle's crossover register imposes
a GLOBAL over-twist that spreads the deviation uniformly — there is no local hotspot for the
per-hotspot greedy to fix, and a single skip barely moves the RMSD.  The fix is the global
skip-DENSITY sweep (:func:`cando_autorefine.sweep_skip_period`): tune the uniform deletion
period to the density that minimises the FEM-vs-intended deviation, exactly as
``skip_twist_tuning`` sweeps the period against the oxDNA twist, but with the fast FEM oracle.

This test proves that end-to-end on a design of the SAME cross-section as the reported failure
(a 3×6 = 18-helix square bundle) but a CI-affordable length.  It builds the strut HEADLESSLY
(the real ``.nadoc`` lives in gitignored ``workspace/`` and would not survive on the other
computer — see the LESSONS on gitignored fixtures) and asserts, via
:func:`tests.automation_harness.assert_fem_autorefine_relieves_twist`, that the refine actually
lands a twist-relieving skip pattern (non-empty ``converged_marks``, big RMSD drop, skips-only,
off crossovers/ends) — the "0 edits" regression can NOT pass it.

Slow (~2-3 min: the density sweep runs ~20 FEM solves on an 18-helix bundle); registered in the
conftest slow registry so ``just test-fast`` skips it.
"""
from __future__ import annotations

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType
from tests.automation_harness import assert_fem_autorefine_relieves_twist

SQ = LatticeType.SQUARE
# 3×6 grid = 18 helices — the cross-section of the reported 3x6x400_Sq_test design.
THREE_BY_SIX = [(r, c) for r in range(3) for c in range(6)]


def _routed_sq_strut(length: int):
    """A fully-routed bare square strut (no marks, no deformation) — the register over-twist is
    the only deviation, so the density sweep is the sole lever."""
    with hb.scratch_session(SQ):
        hb.create_bundle(THREE_BY_SIX, length, lattice=SQ, name="sq3x6")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def test_fem_autorefine_relieves_square_strut_twist_headless():
    """The regression gate: on a bare 18-helix square strut the autorefine must NULL the end-to-end
    twist by landing a real skip density (not the old 0-edit / no-improvement result).

    The objective is TWIST vs the intended twist (exp37 — the deviation-RMSD objective floored twist
    at ~10-15° because RMSD-min sits at a lower density than twist-min).  On the bare 3×6 strut the
    register over-twist is large (tens of degrees); the density sweep + fractional per-helix bumps
    drive it into ±tol while the deviation RMSD is allowed to rise (the twist↔deviation tradeoff).
    Asserted loosely so a slightly different build still passes while the "0 edits" regression fails
    hard."""
    design = _routed_sq_strut(160)
    assert not any(h.loop_skips for h in design.helices)   # bare strut — nothing to greedily fix
    assert not design.deformations

    res = assert_fem_autorefine_relieves_twist(
        design, max_drop_ratio=0.6, min_before_rmsd=0.4, max_hotspots=2)

    # The objective was twist, the density sweep ran (a real period), a per-helix authority map was
    # measured, and the marks are a substantial uniform-ish skip program — the shape of the fix.
    assert res["objective"] == "twist"
    assert res["density"] is not None and res["density"]["best_period"] is not None
    assert res["authority"]                             # per-helix ∂twist/∂skip measured
    n_skips = sum(len(v) for v in res["converged_marks"].values())
    assert n_skips >= len(design.helices)   # at least ~one deletion per helix
