"""Profile-guided adaptive skip refinement (exp32) — pure-function pins (no oxDNA).

Covers the topology-sensitive binning (axial bins partition the core, front bin = low axial),
the signed local-twist extraction, the underdamped secant step (more deletions where over-wound,
fewer where under-wound), and incremental-gap add/remove restricted to a bin.
"""
from __future__ import annotations

import pytest

from backend.api.skip_twist_tuning import build_sq_skip_design, square_cells
from backend.core.profile_guided_refine import (
    bin_layout,
    core_bps,
    counts_per_bin,
    local_twist_per_bin,
    plan_edits,
    secant_targets,
)


@pytest.fixture(scope="module")
def sq_design():
    return build_sq_skip_design(square_cells(2, 3), 40, None)


def test_bins_partition_core_front_to_back(sq_design):
    n = 4
    _edges, ph = bin_layout(sq_design, n)
    for h in sq_design.helices:
        core = set(core_bps(sq_design, h))
        binned = [bp for i in range(n) for bp in ph[h.id][i]]
        assert sorted(binned) == sorted(core)            # every core bp in exactly one bin
        assert len(binned) == len(set(binned))           # no double-assignment
        # front bin (0) holds lower bp than back bin (n-1) — axis sign-normalised consistently
        if ph[h.id][0] and ph[h.id][n - 1]:
            assert max(ph[h.id][0]) < min(ph[h.id][n - 1])


def test_local_twist_per_bin_signs():
    # cumulative flat then ramping → front bins ~0, back bins positive (over-wound)
    prof = [{"position_frac": i / 8, "cum_twist_diff": (0.0 if i <= 4 else (i - 4) * 15.0)}
            for i in range(9)]
    lt = local_twist_per_bin(prof, 4)
    assert lt[0] == pytest.approx(0.0, abs=1e-6)          # flat front
    assert lt[-1] > 10.0                                   # ramping back = over-wound
    assert sum(lt) == pytest.approx(prof[-1]["cum_twist_diff"], abs=1e-6)


def test_secant_round1_adds_where_overwound_removes_where_underwound():
    counts = [4, 4, 4, 4]
    lt = [0.0, 0.0, 30.0, -30.0]                          # bin2 over-wound, bin3 under-wound
    tgt = secant_targets(None, None, counts, lt, gain=1.3)
    assert tgt[0] == 4 and tgt[1] == 4                    # untouched where flat
    assert tgt[2] > 4                                      # add where over-wound
    assert tgt[3] < 4                                      # remove where under-wound


def test_secant_underdamps_more_than_unit_gain():
    counts, lt = [4], [34.0]
    soft = secant_targets(None, None, counts, lt, gain=1.0)[0]
    hard = secant_targets(None, None, counts, lt, gain=1.5)[0]
    assert hard > soft                                    # gain>1 overshoots further


def test_plan_edits_adds_in_overwound_bin(sq_design):
    n = 4
    _e, ph = bin_layout(sq_design, n)
    base = {h.id: [] for h in sq_design.helices}
    cur = counts_per_bin(base, ph)
    target = list(cur)
    target[3] = cur[3] + 2                                # ask for 2 deletions/helix in back bin
    out = plan_edits(base, ph, target)
    h0 = sorted(sq_design.helices, key=lambda x: x.id)[0].id
    placed = set(out.get(h0, []))
    back_bin = set(ph[h0][3])
    assert len(placed & back_bin) == 2                    # landed in the back bin
    assert not (placed - back_bin)                        # nowhere else


def test_plan_edits_removes_to_hit_lower_target(sq_design):
    n = 4
    _e, ph = bin_layout(sq_design, n)
    # seed 3 marks in bin 1 of helix 0, then target 1 → remove 2
    h = sorted(sq_design.helices, key=lambda x: x.id)[0]
    seed = ph[h.id][1][:3]
    skips = {h.id: list(seed)}
    target = counts_per_bin(skips, ph)
    target[1] = 1
    out = plan_edits(skips, ph, target)
    assert len(set(out.get(h.id, [])) & set(ph[h.id][1])) == 1


def test_counts_per_bin_roundtrips(sq_design):
    n = 4
    _e, ph = bin_layout(sq_design, n)
    skips = {h.id: ph[h.id][2][:2] for h in sq_design.helices}   # 2 marks in bin2 each
    c = counts_per_bin(skips, ph)
    assert c[2] == 2 and c[0] == 0 and c[3] == 0
