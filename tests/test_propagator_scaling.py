"""Cost-model logic for the "does an atomistic propagator beat MD at scale?" analysis.

Pure-numpy math tests — no torch, no GPU.  Pins the crossover model's structure and
the load-bearing qualitative conclusions so a future edit can't silently flip them.
"""
import numpy as np

from backend.ml.propagator import scaling as sc


def test_single_point_split_reconstructs_the_point():
    m = sc.fit_namd()   # default single measured point, split by pme_fraction
    got = m.cost_ms(sc.MEASURED_NAMD_N)
    assert abs(got - sc.MEASURED_NAMD_MS_PER_STEP) < 1e-6   # split conserves total


def test_two_points_fit_exactly():
    pts = [(17_827, 6.1), (225_504, 22.0)]   # contrived clean pair
    m = sc.fit_namd(pts)
    for n, y in pts:
        assert abs(m.cost_ms(n) - y) < 1e-3   # exact 2-param fit through 2 points
    assert "fit of 2" in m.provenance


def test_gnn_cost_is_linear_in_n():
    c = sc.gnn_coeff("h64_L2")
    assert abs(c - sc.MEASURED_GNN_MS_AT_5000["h64_L2"] / sc.GNN_BENCH_N) < 1e-12
    # doubling N doubles GNN cost exactly (O(N), no PME)
    n = np.array([1e4, 2e4])
    cost = c * n
    assert abs(cost[1] / cost[0] - 2.0) < 1e-9


def test_accuracy_capable_tier_never_wins_per_step_single_gpu():
    """The honest headline: an accuracy-capable atomistic GNN (h64_L2) does NOT beat
    classical MD per-step at any reachable N, given the measured single-GPU numbers."""
    m = sc.fit_namd()
    assert sc.crossover_n(m, "h64_L2", step_mult=1.0, hybrid_frac=0.0) is None
    # even at a million atoms it is slower (speedup < 1)
    assert sc.speedup(1e6, m, "h64_L2") < 1.0


def test_levers_move_crossover_the_right_way():
    """Bigger stride and a smaller (less accurate) model both help; the model must
    reflect that ordering even though neither makes the accuracy-capable tier win."""
    m = sc.fit_namd()
    s_base = sc.speedup(1e6, m, "h64_L2", step_mult=1.0)
    s_stride = sc.speedup(1e6, m, "h64_L2", step_mult=4.0)
    assert s_stride > s_base                                   # larger step -> faster
    # a tiny model is cheaper per step than an accurate one
    assert sc.gnn_coeff("h16_L1") < sc.gnn_coeff("h128_L3")


def test_overhead_fit_reproduces_controlled_points_and_extrapolates_sanely():
    """The single-GPU regime is fixed-overhead + linear (sub-linear in N); the
    overhead fit must reproduce the two controlled points and, unlike the two-term
    PME fit, extrapolate to a POSITIVE cost at 1e6 atoms."""
    m = sc.fit_namd_overhead()
    for n, y in sc.CONTROLLED_NAMD_POINTS:
        assert abs(m.cost_ms(n) - y) < 1e-6
    assert m.c0 > 0 and m.a > 0                      # real overhead + positive slope
    assert m.cost_ms(1e6) > m.cost_ms(1.4e5) > 0     # monotone, sane extrapolation


def test_two_term_pme_fit_is_degenerate_on_sublinear_data():
    """Documents WHY the overhead model is needed: the measured points are sub-linear
    in N, so the a*N + b*N*log2N fit yields a spurious negative b (nonsense at scale)."""
    m = sc.fit_namd(sc.CONTROLLED_NAMD_POINTS)
    assert m.b < 0                                   # degenerate — do not extrapolate this
    assert m.cost_ms(1e6) < 0                         # the nonsense the overhead fit avoids


def test_accuracy_capable_gnn_is_much_costlier_per_atom_than_namd():
    """Crux: NAMD3 asymptotic per-atom cost is ~0.06 us/atom; an accuracy-capable GNN
    is ~60x that — the reason atomistic-only cannot win at any single-GPU scale."""
    m = sc.fit_namd_overhead()
    ratio = sc.gnn_coeff("h64_L2") / m.a
    assert ratio > 30                                # order ~60x, robustly >>1


def test_report_runs_and_returns_structure():
    out = sc.report()
    assert "tiers" in out and out["tiers"]
    # every lever reports every tier
    for lever, tiers in out["tiers"].items():
        assert set(tiers) == set(sc.MEASURED_GNN_MS_AT_5000)
