"""CanDo FEM deviation map + global RMSD (Phase-5 Item 3).

`compute_deviation` measures, per nucleotide, how far the FEM-predicted shape lands
from the design's intended (displayed) geometry, and reduces it to a single RMSD.
This is the oracle the Item-4 autorefine loop minimises.

The key behaviour (and the Three-Layer Law tie-in): the FEM reads only the
TOPOLOGICAL loop/skip marks.  So a bend drawn as a display-layer DeformationOp but
never realised to loop/skips predicts a STRAIGHT shape → large deviation from the
drawn (bent) geometry.  Realising the loop/skips brings the prediction into agreement
→ the RMSD collapses.  A straight control has ~zero deviation.
"""
from __future__ import annotations


from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.cando_deviation import compute_deviation
from backend.core.models import LatticeType
from backend.physics.fem_solver import predict_shape

HC = LatticeType.HONEYCOMB
SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
LEN = 210


def _routed(*, bend_deg: float | None, realize: bool):
    """A routed 6HB bundle; optionally with a ``bend_deg`` bend program that is either
    realised to loop/skips (``realize=True``) or left as a display-only DeformationOp."""
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB_CELLS, LEN, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        if bend_deg is not None:
            hb.add_bend(0, LEN, curvature_deg_per_bp=bend_deg / LEN)
            if realize:
                hb.apply_loop_skip_deformations()
        return design_state.get_or_404().model_copy(deep=True)


def _deviation(design):
    res = predict_shape(design, nonlinear=False, with_rmsf=False)
    return compute_deviation(design, res["positions"])


def test_deviation_payload_shape_and_stats():
    d = _routed(bend_deg=90.0, realize=True)
    dev = _deviation(d)
    assert dev["n"] > 0
    assert dev["positions"], "one entry per displayed nucleotide"
    for p in dev["positions"][:5]:
        assert set(p) >= {"helix_id", "bp_index", "direction", "backbone_position", "deviation"}
        assert p["deviation"] >= 0.0
    # min ≤ mean ≤ max, and RMSD ≥ mean (quadratic mean dominates the arithmetic mean).
    assert dev["min_deviation"] <= dev["mean_deviation"] <= dev["max_deviation"]
    assert dev["rmsd_nm"] >= dev["mean_deviation"] - 1e-9


def test_straight_control_has_near_zero_deviation():
    """No bend program → FEM predicts straight AND the displayed geometry is straight →
    the shapes coincide → RMSD ≈ 0.  Guards against a spurious baseline deviation."""
    dev = _deviation(_routed(bend_deg=None, realize=False))
    assert dev["rmsd_nm"] < 0.5
    assert dev["max_deviation"] < 1.0


def test_unrealized_bend_deviates_far_more_than_realized():
    """THE deviation-map / autorefine signal.  The SAME 90° bend program:

      • realised to loop/skips → FEM predicts ~85° ≈ the drawn 90° → small RMSD.
      • left as a display-only DeformationOp (loop/skips NOT updated) → FEM predicts a
        STRAIGHT rod ≠ the drawn bend → large RMSD.

    Realising the loop/skips must collapse the deviation — the quantity Item-4
    autorefine drives down."""
    realized = _deviation(_routed(bend_deg=90.0, realize=True))
    display_only = _deviation(_routed(bend_deg=90.0, realize=False))

    assert display_only["rmsd_nm"] > 3.0            # straight FEM vs a drawn ~90° bend
    assert realized["rmsd_nm"] < 3.0                # realised loop/skips ≈ the drawn shape
    # Realising the marks at least halves the deviation — the unambiguous refine signal.
    assert realized["rmsd_nm"] < 0.5 * display_only["rmsd_nm"]


def test_loop_copies_each_get_their_own_deviation_entry():
    """Loop-insert bases (copies at the same helix/bp/direction) must each get their
    own deviation entry keyed by copy — not collapse onto copy 0.  compute_deviation
    matches native per (helix, bp, dir, COPY), so every loop copy is measured and
    coloured; a collapse would leave the extra loop beads uncoloured in the map."""
    from collections import Counter

    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        d = design_state.get_or_404()
        for h in d.helices:                   # +1 → loop inserts (extra copies)
            for bp in (30, 40, 50):
                hb.loop_skip(h.id, bp, 1)
        d = design_state.get_or_404().model_copy(deep=True)

    res = predict_shape(d, nonlinear=False, with_rmsf=False)
    dev = compute_deviation(d, res["positions"])

    # Every entry carries a copy; some keys have copy > 0 (the loop inserts).
    assert all("copy" in p for p in dev["positions"])
    per_key = Counter((p["helix_id"], p["bp_index"], p["direction"]) for p in dev["positions"])
    assert any(v > 1 for v in per_key.values()), "expected loop keys with multiple copies"
    # Distinct (helix, bp, dir, copy) tuples == number of entries → no copy collapsed.
    keyed = {(p["helix_id"], p["bp_index"], p["direction"], p["copy"]) for p in dev["positions"]}
    assert len(keyed) == len(dev["positions"])
    assert dev["n"] == len(dev["positions"])          # every entry matched a native copy


def test_unmatched_positions_excluded_from_stats():
    """A display position with no matching design nucleotide contributes deviation 0 and
    is excluded from the matched count ``n`` (defensive — the display list is normally
    built from the same nucleotides, so this should not happen in practice)."""
    d = _routed(bend_deg=None, realize=False)
    phantom = [{"helix_id": "nope", "bp_index": 9999, "direction": "forward",
                "backbone_position": [1.0, 2.0, 3.0]}]
    dev = compute_deviation(d, phantom)
    assert dev["n"] == 0
    assert dev["positions"][0]["deviation"] == 0.0
    assert dev["rmsd_nm"] == 0.0
