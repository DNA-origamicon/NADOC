"""CanDo-FEM autorefine (Phase-5 Item 4) — the greedy loop/skip refiner driven by the fast FEM
shape oracle.

Two layers of coverage:
  * PURE helpers (no FEM solve) — deviation-field aggregation, hotspot ranking, the
    off-crossover/off-end candidate filter ([[feedback_loopskip_no_crossover_ends]]), candidate
    enumeration, and the mark bookkeeping.  These are the fast, load-bearing invariants.
  * The oracle + greedy loop end-to-end on real routed 6HB designs (linear FEM, small bundles):
    the RMSD never rises, kept edits improve it, a flat design yields no edits, and — the
    topological gate — every mark the refiner lands sits off crossovers/ends.
"""
from __future__ import annotations

import pytest

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core import cando_autorefine as car
from backend.core.models import LatticeType

HC = LatticeType.HONEYCOMB
SQ = LatticeType.SQUARE
SIX_HB_CELLS = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
FOUR_HB_SQ_CELLS = [(0, 0), (1, 0), (0, 1), (1, 1)]


# ── Fixtures ────────────────────────────────────────────────────────────────────────────────

def _routed_bend(length: int, bend_deg: float | None, *, realize: bool):
    """A fully-routed 6HB honeycomb bundle; optional bend program either realised to loop/skips
    or left as a display-only DeformationOp (so there is deviation for the refiner to shrink)."""
    with hb.scratch_session(HC):
        hb.create_bundle(SIX_HB_CELLS, length, lattice=HC, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        if bend_deg is not None:
            hb.add_bend(0, length, curvature_deg_per_bp=bend_deg / length)
            if realize:
                hb.apply_loop_skip_deformations()
        return design_state.get_or_404().model_copy(deep=True)


def _routed_sq(length: int = 128):
    with hb.scratch_session(SQ):
        hb.create_bundle(FOUR_HB_SQ_CELLS, length, lattice=SQ, name="4hb_sq")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


SIX_HB_SQ_CELLS = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]


@pytest.fixture(scope="module")
def routed_sq_strut():
    """A LONG bare square-lattice bundle (no marks, no deformation).  Its crossover register
    imposes an intrinsic global over-twist that only a skip DENSITY can relieve — the case the
    per-hotspot greedy can't touch (uniform twist → no local hotspot).  Module-scoped: the density
    sweep solves the FEM ~20× so we build it once."""
    with hb.scratch_session(SQ):
        hb.create_bundle(SIX_HB_SQ_CELLS, 256, lattice=SQ, name="sq6")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


# ── Pure helpers ──────────────────────────────────────────────────────────────────────────────

def test_aggregate_deviation_by_bp_averages_directions_and_copies():
    positions = [
        {"helix_id": "h0", "bp_index": 5, "deviation": 1.0},
        {"helix_id": "h0", "bp_index": 5, "deviation": 3.0},   # other strand / copy at same station
        {"helix_id": "h0", "bp_index": 9, "deviation": 2.0},
    ]
    field = car.aggregate_deviation_by_bp(positions)
    assert field[("h0", 5)] == pytest.approx(2.0)   # mean of 1 and 3
    assert field[("h0", 9)] == pytest.approx(2.0)


def test_rank_hotspots_threshold_spacing_and_empty():
    # A flat field (all equal) has zero std → nothing exceeds mean → no hotspots (do-no-harm).
    flat = {("h0", i): 1.0 for i in range(10)}
    assert car.rank_hotspots(flat) == []
    # One clear outlier is picked; others below mean+std are not.
    field = {("h0", i): 0.1 for i in range(10)}
    field[("h0", 3)] = 10.0
    field[("h0", 7)] = 8.0
    hs = car.rank_hotspots(field, sigma=1.0, max_hotspots=8, min_spacing=2)
    assert hs[0] == ("h0", 3)                        # most-severe first
    # min_spacing de-dups near-neighbours on the same helix.
    dense = {("h0", i): float(10 - i) for i in range(6)}  # 0 highest, all above? tune spacing
    picked = car.rank_hotspots(dense, sigma=0.0, max_hotspots=8, min_spacing=3)
    for a in range(len(picked)):
        for b in range(a + 1, len(picked)):
            if picked[a][0] == picked[b][0]:
                assert abs(picked[a][1] - picked[b][1]) >= 3


def test_candidate_edits_mode_and_remove_gating():
    free = {"h0": [10, 20, 30]}
    # No existing marks → only ADD ops; square mode omits add_loop.
    sq = car.candidate_edits(("h0", 12), {}, free, allow_loops=False)
    assert {e["op"] for e in sq} == {"add_skip"}
    assert all(e["bp_index"] == 10 for e in sq)      # nearest free bp to 12
    hc = car.candidate_edits(("h0", 12), {}, free, allow_loops=True)
    assert {e["op"] for e in hc} == {"add_skip", "add_loop"}
    # An existing mark on the helix enables a remove targeting the nearest one.
    withmark = car.candidate_edits(("h0", 12), {"h0": {25: -1}}, free, allow_loops=False)
    rm = [e for e in withmark if e["op"] == "remove"]
    assert rm and rm[0]["bp_index"] == 25
    # No free candidates → no ADD ops (nowhere legal to place).
    none_free = car.candidate_edits(("h0", 12), {}, {"h0": []}, allow_loops=True)
    assert none_free == []


def test_with_edit_add_and_remove_semantics():
    marks = {"h0": {25: -1}}
    assert car._with_edit(marks, {"helix_id": "h0", "op": "add_skip", "bp_index": 10})["h0"][10] == -1
    assert car._with_edit(marks, {"helix_id": "h0", "op": "add_loop", "bp_index": 10})["h0"][10] == +1
    removed = car._with_edit(marks, {"helix_id": "h0", "op": "remove", "bp_index": 25})
    assert "h0" not in removed                        # last mark gone → helix key dropped
    # original is untouched (copy semantics)
    assert marks == {"h0": {25: -1}}


def test_apply_marks_sets_exactly_the_mark_set():
    d = _routed_bend(84, None, realize=False)
    hid = d.helices[0].id
    out = car.apply_marks(d, {hid: {30: -1, 40: +1}})
    marks = car.current_marks_by_helix(out)
    assert marks == {hid: {30: -1, 40: +1}}
    # clearing wins: apply an empty set → no marks anywhere.
    assert car.current_marks_by_helix(car.apply_marks(out, {})) == {}


# ── The topological gate: off-crossover / off-end placement ─────────────────────────────────────

def test_free_interior_candidates_excludes_crossovers_endpoints_and_margin():
    d = _routed_bend(126, None, realize=False)
    forbidden, interior = car._forbidden_bps(d)
    # Crossover bps + domain endpoints are in the forbidden set for their helix.
    for xo in d.crossovers:
        for half in (xo.half_a, xo.half_b):
            assert half.index in forbidden[half.helix_id]
    for h in d.helices:
        cands = car.free_interior_candidates(d, h, forbidden[h.id])
        # No candidate lands on any forbidden bp (crossover / endpoint / end margin).
        assert not (set(cands) & forbidden[h.id])
        lo, hi = interior[h.id]
        assert all(lo <= c <= hi for c in cands)


# ── Oracle + greedy loop (real linear FEM on small bundles) ─────────────────────────────────────

def test_fem_measure_returns_rmsd_and_field():
    d = _routed_bend(105, 60.0, realize=True)
    m = car.fem_measure(d, nonlinear=False)
    assert m is not None
    assert m["rmsd"] >= 0.0 and m["n"] > 0
    assert m["deviation_by_bp"]                        # per-(helix,bp) field present


def test_refine_straight_control_makes_no_edits():
    d = _routed_bend(105, None, realize=False)          # straight, no marks → no hotspots
    res = car.fem_refine(d, nonlinear=False, max_hotspots=4)
    assert res["status"] == "done"
    assert res["edits_kept"] == []
    assert res["after"]["rmsd"] == pytest.approx(res["before"]["rmsd"])
    assert res["converged_marks"] == {}


def test_refine_honeycomb_shape_hits_bend_and_places_marks_off_forbidden():
    # An under-realised 90° bend: keep the DeformationOp target but strip half the loop/skips so the
    # FEM under-bends → a real shape error opens up.  A programmed bend >> the arc-bend noise floor
    # routes to the COUPLED (twist,bend) shape solve (exp38/G1), which drives the bend toward target.
    realized = _routed_bend(210, 90.0, realize=True)
    marks = car.current_marks_by_helix(realized)
    reduced = {hid: {bp: dl for i, (bp, dl) in enumerate(sorted(bps.items())) if i % 2 == 0}
               for hid, bps in marks.items()}
    under = car.apply_marks(realized, reduced)          # keeps the bend DeformationOp
    res = car.fem_refine(under, nonlinear=False)

    assert res["status"] == "done"
    assert res["objective"] == "shape"                  # programmed bend → coupled twist+bend solve
    assert res["mode"] == "loops_and_skips"             # honeycomb → loops allowed
    assert res["authority"] is not None                 # per-helix [∂twist/∂skip, ∂bend/∂skip] map
    # The coupled solve never regresses the shape: bend lands NO FURTHER from target than it started
    # (it only adopts a step that lowers the combined twist+bend error; deviation RMSD may rise).
    tgt_bd = res["bend_target"]
    assert abs(res["bend_after"] - tgt_bd) <= abs(res["bend_before"] - tgt_bd) + 1e-6
    # Any mark the refiner ADDED (beyond the inherited under-realised set) sits off crossovers/ends
    # ([[feedback_loopskip_no_crossover_ends]]); inherited realizer marks may sit on crossovers.
    forbidden, _ = car._forbidden_bps(under)
    inherited = {(hid, bp) for hid, bps in reduced.items() for bp in bps}
    for hid, bps in res["converged_marks"].items():
        for bp in bps:
            if (hid, bp) not in inherited:
                assert bp not in forbidden[hid], "shape solve ADDED a mark on a crossover/end"


def test_refine_emits_per_iteration_twist_bend_deviation_and_target():
    # The live-status readout: each iteration event carries current {deviation, bend_deg, twist_deg}
    # vs the target, and the target deviation is 0 (perfect match).  On a bend design the bend is
    # measured (not None) and the target bend is a real arc angle > the under-realized current.
    realized = _routed_bend(126, 90.0, realize=True)
    marks = car.current_marks_by_helix(realized)
    reduced = {hid: {bp: dl for i, (bp, dl) in enumerate(sorted(bps.items())) if i % 2 == 0}
               for hid, bps in marks.items()}
    under = car.apply_marks(realized, reduced)

    events = []
    res = car.fem_refine(under, nonlinear=False, max_hotspots=4, rmsd_improve_nm=0.02,
                         on_progress=events.append)
    iters = [e for e in events if e["phase"] == "iteration"]
    assert iters, "at least the baseline (iteration 0) event is emitted"
    assert iters[0]["iteration"] == 0
    for e in iters:
        for side in ("current", "target"):
            assert set(e[side]) == {"deviation", "twist_deg", "bend_deg"}
        assert e["target"]["deviation"] == 0.0
        # bend/twist are resolvable on a routed multi-helix bundle
        assert e["current"]["bend_deg"] is not None and e["target"]["bend_deg"] is not None
    # Target bend is a real arc angle; the FEM under-realizes it (current < target).
    assert iters[-1]["target"]["bend_deg"] > 10.0
    assert res["metrics"]["target"]["deviation"] == 0.0
    assert set(res["metrics"]) == {"before", "after", "target"}


def test_measure_bundle_arc_bend_reads_zero_on_straight_and_angle_on_arc():
    from backend.core.oxdna_health import measure_bundle_arc_bend
    import numpy as np
    # A straight 3-helix bundle → ~0.  Points as {helix_id, bp_index, backbone_position}.
    straight = [{"helix_id": f"h{k}", "bp_index": i,
                 "backbone_position": [float(k), 0.0, float(i)]}
                for k in range(3) for i in range(40)]
    assert measure_bundle_arc_bend(straight) == pytest.approx(0.0, abs=2.0)
    # A quarter-circle arc of the bundle centreline → ~90°.
    arc = []
    for i in range(40):
        th = (np.pi / 2) * i / 39.0
        cx, cz = 50.0 * np.sin(th), 50.0 * (1 - np.cos(th))
        for k in range(3):
            arc.append({"helix_id": f"h{k}", "bp_index": i,
                        "backbone_position": [cx + float(k), 0.0, cz]})
    assert measure_bundle_arc_bend(arc) == pytest.approx(90.0, abs=10.0)


# ── Global skip-DENSITY search (SQUARE register over-twist) ─────────────────────────────────────

def test_periodic_skip_marks_are_skips_only_off_forbidden_and_empty_for_honeycomb():
    # Honeycomb has no register-twist knob → no periodic pattern.
    hc = _routed_bend(84, None, realize=False)
    assert car.periodic_skip_marks(hc, 48) == {}
    # Square: one deletion per `period` bp per helix, all skips (−1), none on a forbidden bp.
    sq = _routed_sq(128)
    marks = car.periodic_skip_marks(sq, 48)
    assert marks and all(dl == -1 for bps in marks.values() for dl in bps.values())
    forbidden, _ = car._forbidden_bps(sq)
    for hid, bps in marks.items():
        assert not (set(bps) & forbidden[hid]), "a periodic skip landed on a crossover/end"
    # A denser period places strictly more skips than a sparser one.
    assert (sum(len(v) for v in car.periodic_skip_marks(sq, 24).values())
            > sum(len(v) for v in marks.values()))


def test_sweep_skip_period_finds_a_twist_relieving_minimum(routed_sq_strut):
    # The register over-twist makes the 0-skip strut deviate; the sweep must find a skip DENSITY
    # that lowers the RMSD well below the bare bundle and report the sampled curve.
    sweep = car.sweep_skip_period(routed_sq_strut, nonlinear=False)
    assert sweep["status"] == "done"
    base_rmsd = sweep["baseline_measure"]["rmsd"]
    assert sweep["best_period"] is not None, "adding skips must beat the bare (0-skip) strut"
    assert 16 <= sweep["best_period"] <= 128            # near the ~48 bp literature density
    assert sweep["best_measure"]["rmsd"] < 0.75 * base_rmsd   # a substantial straightening
    assert all(dl == -1 for bps in sweep["best_marks"].values() for dl in bps.values())
    periods = {c["period"] for c in sweep["curve"]}
    assert None in periods and len([p for p in periods if p is not None]) >= 6


def test_refine_plain_square_strut_nulls_twist_where_greedy_kept_zero(routed_sq_strut):
    # THE regression + the exp37 objective change: on a plain square strut the per-hotspot greedy
    # kept 0 edits (uniform twist → no local hotspot).  The refiner now targets end-to-end TWIST vs
    # the intended twist — a density sweep to the twist-nulling density + fractional per-helix bumps
    # — and drives the twist into ±tol (the deviation RMSD is allowed to rise; it is not the goal).
    res = car.fem_refine(routed_sq_strut, nonlinear=False)
    assert res["status"] == "done"
    assert res["mode"] == "skips_only"
    assert res["objective"] == "twist"
    # The density report is present (the sweep ran) and a per-helix authority map was measured.
    assert res["density"] is not None and res["density"]["best_period"] is not None
    assert res["authority"] and len(res["authority"]) >= 1
    # The twist error vs the intended twist collapses (a bare strut is strongly over-wound).
    tgt = res["twist_target"]
    err_before = abs(res["twist_before"] - tgt)
    err_after = abs(res["twist_after"] - tgt)
    assert err_before > 5.0                       # register over-twist is large on a bare strut
    assert err_after < 0.5 * err_before           # substantially nulled
    # A non-empty, skips-only converged pattern (greedy alone produced {} here).
    marks = res["converged_marks"]
    assert marks and all(dl == -1 for bps in marks.values() for dl in bps.values())
    # Every landed skip is off crossovers/ends.
    forbidden, _ = car._forbidden_bps(routed_sq_strut)
    for hid, bps in marks.items():
        assert not (set(bps) & forbidden[hid])


def test_sweep_honors_should_stop(routed_sq_strut):
    # A should_stop that trips immediately → the sweep bails as 'stopped' with the 0-skip point.
    sweep = car.sweep_skip_period(routed_sq_strut, nonlinear=False, should_stop=lambda: True)
    assert sweep["status"] == "stopped"
    assert sweep["best_period"] is None      # nothing beat the (unmeasured) baseline


def test_refine_square_lattice_is_skips_only():
    d = _routed_sq(128)
    # Seed a couple of skips so there is a pattern to tune (still square → skips only).
    from backend.core.loop_skip_calculator import sq_lattice_periodic_skips
    from backend.core.loop_skip_calculator import apply_loop_skips
    d = apply_loop_skips(d, sq_lattice_periodic_skips(d, 48))
    res = car.fem_refine(d, nonlinear=False, max_hotspots=3, rmsd_improve_nm=0.02)
    assert res["mode"] == "skips_only"
    # No loop (+1) may ever appear in a square-lattice refinement.
    for bps in res["converged_marks"].values():
        assert all(dl == -1 for dl in bps.values())
