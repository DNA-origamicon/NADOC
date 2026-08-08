"""Phase 5 — regional (non-uniform) skip placement + per-(helix,bp) strain field.

Pure-function pins (no oxDNA / no GPU): the load-bearing anti-clustering guarantee, the
deviation-attracts / strain-repels biasing, budget = net-twist preservation, determinism,
and the strain-field aggregation.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.api.skip_twist_tuning import build_sq_skip_design, square_cells
from backend.core import oxdna_health as health
from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.core.models import Design, LatticeType
from backend.core.regional_skip_placer import (
    aggregate_deviation_per_bp,
    budget_from_uniform_period,
    core_candidates,
    place_regional_skips,
)


@pytest.fixture(scope="module")
def sq_design():
    """A routed, sequenced 2x3x40 square-lattice bundle, no skips (the candidate source)."""
    return build_sq_skip_design(square_cells(2, 3), 40, None)


def _first_helix_with_budget(design, budget_per_helix, want=3):
    for h in sorted(design.helices, key=lambda h: h.id):
        if (
            len(core_candidates(design, h)) >= want * 4
            and budget_per_helix.get(h.id, 0) >= want
        ):
            return h
    # fall back: any helix with candidates
    for h in sorted(design.helices, key=lambda h: h.id):
        if core_candidates(design, h):
            return h
    raise AssertionError("no helix with dsDNA-core candidates")


def test_budget_respected_and_core_only(sq_design):
    budget = {h.id: 4 for h in sq_design.helices}
    mods = place_regional_skips(sq_design, budget, {}, {})
    assert mods, "expected placements"
    for h in sq_design.helices:
        cands = set(core_candidates(sq_design, h))
        placed = mods.get(h.id, [])
        # count equals min(budget, candidates) → net twist density preserved
        assert len(placed) == min(4, len(cands))
        for ls in placed:
            assert ls.delta == -1
            assert ls.bp_index in cands  # never on ss ends / outside core


def test_anti_clustering_one_per_even_slot(sq_design):
    """The guarantee: with flat fields each deletion sits in its OWN even slot, so the
    cumulative-deletion staircase tracks the linear ideal — an end-clustered pattern
    (same net twist, wrong middle) is impossible."""
    budget_n = 5
    budget = {h.id: budget_n for h in sq_design.helices}
    mods = place_regional_skips(sq_design, budget, {}, {})
    for h in sq_design.helices:
        cands = core_candidates(sq_design, h)
        m = len(cands)
        placed = mods.get(h.id, [])
        if len(placed) < budget_n:
            continue
        idxs = sorted(cands.index(ls.bp_index) for ls in placed)
        for k, i in enumerate(idxs):
            lo = (k * m) // budget_n
            hi = max(lo + 1, ((k + 1) * m) // budget_n)
            assert lo <= i < hi, f"pick {i} (helix {h.id}) escaped slot [{lo},{hi})"


def test_deviation_attracts(sq_design):
    budget = budget_from_uniform_period(sq_design, 24)
    h = _first_helix_with_budget(sq_design, budget)
    cands = core_candidates(sq_design, h)
    m, b = len(cands), budget[h.id]
    # Spike deviation at the candidate in the MIDDLE of slot 1 → it should win that slot.
    lo, hi = (1 * m) // b, max(2, (2 * m) // b)
    target_idx = (lo + hi) // 2
    target_bp = cands[target_idx]
    dev = {(h.id, target_bp): 100.0}
    mods = place_regional_skips(sq_design, budget, dev, {}, w_dev=1.0, w_strain=0.0)
    assert any(ls.bp_index == target_bp for ls in mods[h.id]), (
        "deviation spike not targeted"
    )


def test_strain_repels(sq_design):
    budget = budget_from_uniform_period(sq_design, 24)
    h = _first_helix_with_budget(sq_design, budget)
    cands = core_candidates(sq_design, h)
    m, b = len(cands), budget[h.id]
    lo, hi = (1 * m) // b, max(2, (2 * m) // b)
    assert hi - lo >= 2, "need a multi-candidate slot for this assertion"
    spike_idx = (lo + hi) // 2
    spike_bp = cands[spike_idx]
    strain = {(h.id, spike_bp): 100.0}
    mods = place_regional_skips(sq_design, budget, {}, strain, w_dev=1.0, w_strain=1.0)
    assert all(ls.bp_index != spike_bp for ls in mods[h.id]), (
        "placed onto a strain hotspot"
    )


def test_min_spacing_respected(sq_design):
    budget = {h.id: 6 for h in sq_design.helices}
    mods = place_regional_skips(sq_design, budget, {}, {}, min_spacing=4)
    for placed in mods.values():
        bps = sorted(ls.bp_index for ls in placed)
        gaps = [b - a for a, b in zip(bps, bps[1:])]
        assert all(g >= 4 for g in gaps), f"min-spacing violated: {gaps}"


def test_deterministic(sq_design):
    budget = budget_from_uniform_period(sq_design, 24)
    dev = {
        (h.id, core_candidates(sq_design, h)[0]): 5.0
        for h in sq_design.helices
        if core_candidates(sq_design, h)
    }
    a = place_regional_skips(sq_design, budget, dev, {})
    b = place_regional_skips(sq_design, budget, dev, {})
    assert {k: [(s.bp_index, s.delta) for s in v] for k, v in a.items()} == {
        k: [(s.bp_index, s.delta) for s in v] for k, v in b.items()
    }


def test_budget_matches_uniform_density(sq_design):
    """Regional placement preserves the per-helix COUNT of the uniform period it derives
    from → identical net-twist density, only WHERE differs."""
    from backend.core.loop_skip_calculator import sq_lattice_periodic_skips

    period = 24
    uniform = sq_lattice_periodic_skips(sq_design, period)
    budget = budget_from_uniform_period(sq_design, period)
    assert budget == {h: len(s) for h, s in uniform.items()}
    mods = place_regional_skips(sq_design, budget, {}, {})
    for hid, count in budget.items():
        assert len(mods.get(hid, [])) == min(
            count,
            len(
                core_candidates(
                    sq_design, next(h for h in sq_design.helices if h.id == hid)
                )
            ),
        )


def test_non_square_returns_empty():
    d = Design(lattice_type=LatticeType.HONEYCOMB)
    assert place_regional_skips(d, {"h": 3}, {}, {}) == {}


def test_aggregate_deviation_per_bp_averages_strands():
    dmap = {
        "positions": [
            {"helix_id": "H", "bp_index": 0, "direction": "fwd", "deviation": 2.0},
            {"helix_id": "H", "bp_index": 0, "direction": "rev", "deviation": 4.0},
            {"helix_id": "H", "bp_index": 1, "direction": "fwd", "deviation": 1.0},
        ]
    }
    agg = aggregate_deviation_per_bp(dmap)
    assert agg[("H", 0)] == pytest.approx(3.0)  # mean of both strands
    assert agg[("H", 1)] == pytest.approx(1.0)


def test_build_regional_skip_design_preserves_count_and_resequences():
    """The regional build lays the SAME per-helix deletion COUNT as the uniform period
    (net-twist density preserved) and re-sequences so the design stays oxDNA-ready."""
    from backend.api.skip_twist_tuning import (
        build_regional_skip_design,
        build_sq_skip_design,
    )
    from backend.core.loop_skip_calculator import sq_lattice_periodic_skips
    from backend.physics.oxdna_interface import designed_pair_complementarity

    base = build_sq_skip_design(square_cells(2, 3), 60, None)
    period = 24
    uniform_total = sum(
        len(s) for s in sq_lattice_periodic_skips(base, period).values()
    )

    regional = build_regional_skip_design(
        base, period, {}, {}
    )  # empty fields => even spread
    reg_total = sum(len(h.loop_skips) for h in regional.helices)
    assert reg_total == uniform_total > 0  # identical density

    n_comp, n_pairs = designed_pair_complementarity(regional)
    assert n_pairs > 0 and n_comp / n_pairs > 0.95  # re-sequenced, oxDNA-ready


def test_build_explicit_skip_from_design_lays_exact_pattern():
    """The apply path for a converged regional pattern lays the caller's EXACT deletion
    set (and re-sequences)."""
    from backend.api.skip_twist_tuning import (
        build_explicit_skip_from_design,
        build_sq_skip_design,
    )
    from backend.physics.oxdna_interface import designed_pair_complementarity

    base = build_sq_skip_design(square_cells(2, 3), 60, None)
    h = next(hh for hh in base.helices if len(core_candidates(base, hh)) >= 3)
    want = core_candidates(base, h)[1:4]  # three interior positions
    built = build_explicit_skip_from_design(base, {h.id: want})

    bh = next(hh for hh in built.helices if hh.id == h.id)
    assert sorted(ls.bp_index for ls in bh.loop_skips) == sorted(want)
    assert all(ls.delta == -1 for ls in bh.loop_skips)
    n_comp, n_pairs = designed_pair_complementarity(built)
    assert n_pairs > 0 and n_comp / n_pairs > 0.95


def test_twist_profile_endpoint_matches_scalar_and_is_monotonic():
    """The per-slab cumulative profile's last value == measure_bundle_twist's scalar, and a
    uniformly-twisted bundle accumulates monotonically along the axis."""
    from tests.test_oxdna_relaxation import _twist_bundle

    pos = _twist_bundle(40.0, n_axial=24)
    profile = health.measure_bundle_twist_profile(pos)
    assert len(profile) >= 3
    assert profile[-1][1] == pytest.approx(health.measure_bundle_twist(pos), rel=1e-6)
    vals = [v for _t, v in profile]
    assert vals[-1] > vals[0]  # accumulates one direction
    assert all(
        b >= a - 1e-6 for a, b in zip(vals, vals[1:])
    )  # monotonic non-decreasing


def test_redistribute_follows_overtwist_and_is_deletion_only():
    base = build_sq_skip_design(square_cells(2, 3), 60, None)
    budget = {h.id: 8 for h in base.helices}
    from backend.core.regional_skip_placer import redistribute_by_twist_profile

    # Over-twist concentrated in the MIDDLE axial fifth (s∈[0.4,0.6]); flat elsewhere.
    prof = [(0.0, 0.0), (4.0, 0.0), (6.0, 10.0), (10.0, 10.0)]
    mods = redistribute_by_twist_profile(base, budget, prof, gain=20.0, base=1.0)
    assert mods
    for h in base.helices:
        cands = core_candidates(base, h)
        placed = mods.get(h.id, [])
        assert len(placed) == min(8, len(cands))  # budget (net-twist count) preserved
        assert all(ls.delta == -1 for ls in placed)  # deletions only
        assert all(ls.bp_index in cands for ls in placed)  # core only
        if len(cands) < 10:
            continue
        lo, hi = cands[0], cands[-1]
        rng = (hi - lo) or 1
        frac = [(ls.bp_index - lo) / rng for ls in placed]
        mid = sum(
            1 for f in frac if 0.4 <= f <= 0.6
        )  # the over-wound fifth (20% of span)
        ends = sum(1 for f in frac if f < 0.4 or f > 0.6)  # the flat 80%
        assert mid >= 2  # density concentrates where over-wound
        # denser per-unit-length in the middle than the flat ends
        assert (mid / 0.2) > (ends / 0.8)


def test_redistribute_staggers_across_helices():
    """Deletions must NOT all land in the same cross-sectional slice — each helix's grid is
    phase-shifted by rank (like sq_lattice's offset_i).  Cross-section alignment changes the
    bundle's twist/strain response (it was a ~20° artifact mistaken for refinement)."""
    from backend.core.regional_skip_placer import redistribute_by_twist_profile

    base = build_sq_skip_design(square_cells(2, 3), 40, None)
    budget = {h.id: 2 for h in base.helices}
    mods = redistribute_by_twist_profile(
        base, budget, [(0.0, 0.0), (10.0, 0.0)], gain=0.5, base=1.0
    )  # flat → pure stagger test
    first_local = []
    for h in sorted(base.helices, key=lambda x: x.id):
        ls = sorted(s.bp_index - h.bp_start for s in mods.get(h.id, []))
        if ls:
            first_local.append(ls[0])
    # adjacent helices should be offset (not all identical) — at least half are distinct
    assert len(set(first_local)) > 1
    assert len(set(first_local)) >= max(2, len(first_local) // 2)


def test_detrend_error_profile_removes_net_keeps_shape():
    from backend.core.regional_skip_placer import detrend_error_profile

    # pure linear (all net, no local shape) → detrends to ~0 everywhere
    lin = [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0)]
    assert all(abs(e) < 1e-9 for _t, e in detrend_error_profile(lin))
    # a mid bump on top of a net trend → endpoints 0, middle retains the bump
    bumped = [(0.0, 0.0), (5.0, 8.0), (10.0, 10.0)]
    d = detrend_error_profile(bumped)
    assert abs(d[0][1]) < 1e-9 and abs(d[-1][1]) < 1e-9  # endpoints zeroed
    assert d[1][1] == pytest.approx(3.0)  # 8 − (linear 5) = 3 bump survives


def test_redistribute_flat_profile_spreads_evenly():
    """A flat error profile (no over-twist) => uniform-like even spread (anti-clustering)."""
    from backend.core.regional_skip_placer import redistribute_by_twist_profile

    base = build_sq_skip_design(square_cells(2, 3), 60, None)
    budget = {h.id: 6 for h in base.helices}
    mods = redistribute_by_twist_profile(
        base, budget, [(0.0, 0.0), (10.0, 0.0)], gain=20.0, base=1.0, min_spacing=4
    )
    for h in base.helices:
        placed = sorted(ls.bp_index for ls in mods.get(h.id, []))
        if len(placed) < 3:
            continue
        gaps = [b - a for a, b in zip(placed, placed[1:])]
        assert max(gaps) <= 3 * (
            sum(gaps) / len(gaps)
        )  # no clustering — gaps stay even-ish


def _bundle_positions(kink_z=0.0):
    """Synthetic 2-helix bundle along x (y=±1); for x past the midpoint add `kink_z`·(x−mid)
    to bow the axis — bp midpoints then deflect, exercising measure_bundle_bend."""
    out, n = [], 40
    mid = n / 2
    for bp in range(n):
        x = float(bp)
        z = kink_z * max(0.0, x - mid)
        for hid, y, d in (("A", 1.0, "fwd"), ("B", -1.0, "rev")):
            out.append(
                {
                    "helix_id": hid,
                    "bp_index": bp,
                    "direction": d,
                    "backbone_position": [x, y, z],
                }
            )
    return out


def test_measure_bundle_bend_straight_vs_bent():
    straight = health.measure_bundle_bend(_bundle_positions(kink_z=0.0))
    bent = health.measure_bundle_bend(_bundle_positions(kink_z=0.5))
    assert straight < 2.0  # collinear centroids → ~0
    assert bent > 15.0  # a real kink deflects the axis
    assert bent > straight + 10.0


def test_backbone_strain_field_aggregates_per_bp(monkeypatch):
    """Per-bond |length - R0| in oxDNA units, attributed to each touched (helix,bp) by MAX
    (worst-case local strain), strands collapsed by MAX."""
    R0 = health.FENE_R0_OXDNA2
    a, b, c = ("H", 0, "fwd"), ("H", 1, "fwd"), ("H", 2, "fwd")
    monkeypatch.setattr(health, "backbone_bond_pairs", lambda design: [(a, b), (b, c)])
    monkeypatch.setattr(
        health, "oxdna_backbone_site", lambda pos, a1, a3: pos
    )  # identity
    U = OXDNA_LENGTH_UNIT
    full_map = {
        a: {"backbone_position": np.array([0.0, 0, 0]), "a1": 0, "a3": 0},
        b: {
            "backbone_position": np.array([R0 * U, 0, 0]),
            "a1": 0,
            "a3": 0,
        },  # a-b ≈ R0 → 0 strain
        c: {
            "backbone_position": np.array([R0 * U + 2.0 * U, 0, 0]),
            "a1": 0,
            "a3": 0,
        },  # b-c = 2.0 units
    }
    field = health.backbone_strain_field(object(), full_map)
    assert field[("H", 0)] == pytest.approx(0.0, abs=1e-6)  # only the relaxed bond
    assert field[("H", 2)] == pytest.approx(
        2.0 - R0, abs=1e-6
    )  # only the stretched bond
    assert field[("H", 1)] == pytest.approx(2.0 - R0, abs=1e-6)  # touches both → MAX
